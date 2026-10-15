"""Editor geometry: handles, resize in the rotated frame, snapping, hit tests.

Run: python -m unittest scena_editor.tests.test_editor_geometry
"""
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import assume, given, strategies as hst  # noqa: E402

from scena_editor import geometry as geo  # noqa: E402


def rect(cx=0.0, cy=0.0, w=100.0, h=40.0, r=0.0, kind="rect"):
    return {"kind": kind, "center": (cx, cy), "width": w, "height": h, "angle": r}


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


_coord = hst.floats(-1000, 1000, allow_nan=False)
_extent = hst.floats(1, 500, allow_nan=False)
_angle = hst.floats(0, 360, allow_nan=False, exclude_max=True)
_signs = hst.sampled_from(geo.HANDLE_SIGNS)


class TestResize(unittest.TestCase):
    @given(cx=_coord, cy=_coord, w=_extent, h=_extent, r=_angle, signs=_signs,
           px=_coord, py=_coord)
    def test_opposite_handle_stays_fixed(self, cx, cy, w, h, r, signs, px, py):
        item = rect(cx, cy, w, h, r)
        anchor = geo.anchor_for(item, signs)
        new = {**item, **geo.resize(item, signs, anchor, (px, py))}
        # The fixed point is still a handle point of the new rect (dragging past
        # it flips the rect, so its name may change, not its place).
        points = [(h_.x, h_.y) for h_ in geo.handles(new, 0) if h_.role == "resize"]
        self.assertTrue(any(close(p, anchor, 1e-6) for p in points), (anchor, points))

    @given(cx=_coord, cy=_coord, w=_extent, h=_extent, r=_angle, signs=_signs,
           px=_coord, py=_coord)
    def test_dragged_handle_follows_the_pointer_on_its_axes(self, cx, cy, w, h, r, signs,
                                                            px, py):
        item = rect(cx, cy, w, h, r)
        anchor = geo.anchor_for(item, signs)
        new = {**item, **geo.resize(item, signs, anchor, (px, py))}
        # In the item's frame, the moved handle sits at the pointer on the axes
        # it controls (the other axis keeps its size).
        lp = geo.rot(px - anchor[0], py - anchor[1], -r)
        sx, sy = signs
        if sx:
            self.assertAlmostEqual(new["width"], abs(lp[0]), places=6)
        else:
            self.assertAlmostEqual(new["width"], w, places=6)
        if sy:
            self.assertAlmostEqual(new["height"], abs(lp[1]), places=6)
        else:
            self.assertAlmostEqual(new["height"], h, places=6)

    def test_keep_aspect_scales_both(self):
        item = rect(0, 0, 100, 50, 0, kind="image")
        anchor = geo.anchor_for(item, (1, 1))
        new = geo.resize(item, (1, 1), anchor, (150, 10))
        self.assertEqual((new["width"], new["height"]), (200.0, 35.0))
        new = geo.resize(item, (1, 1), anchor, (150, 10), keep_aspect=True)
        self.assertAlmostEqual(new["width"] / new["height"], 2.0)
        self.assertAlmostEqual(new["width"], 200.0)

    def test_angle_toward(self):
        self.assertAlmostEqual(geo.angle_toward((0, 0), (0, 10)), 0.0)
        self.assertAlmostEqual(geo.angle_toward((0, 0), (-10, 0)), 90.0)


class TestSnap(unittest.TestCase):
    @given(v=_coord, grid=hst.sampled_from([1.0, 5.0, 10.0, 20.0]))
    def test_snap_is_idempotent_and_on_grid(self, v, grid):
        s = geo.snap(v, grid)
        self.assertEqual(geo.snap(s, grid), s)
        self.assertAlmostEqual((s / grid) - round(s / grid), 0.0)
        self.assertLessEqual(abs(s - v), grid / 2 + 1e-9)

    @given(rx=_coord, ry=_coord, dx=_coord, dy=_coord)
    def test_snapped_move_puts_the_reference_on_the_grid(self, rx, ry, dx, dy):
        sdx, sdy = geo.snapped_delta((rx, ry), dx, dy, 10.0)
        self.assertAlmostEqual(((rx + sdx) / 10) - round((rx + sdx) / 10), 0.0, places=6)
        self.assertAlmostEqual(((ry + sdy) / 10) - round((ry + sdy) / 10), 0.0, places=6)

    def test_angle_snap(self):
        self.assertEqual(geo.snap_angle(22.0), 15.0)
        self.assertEqual(geo.snap_angle(359.0), 0.0)

    def test_zero_grid_is_free(self):
        self.assertEqual(geo.snap(3.3, 0.0), 3.3)

    def test_nearest_corner(self):
        box = (0.0, 0.0, 40.0, 20.0)
        self.assertEqual(geo.nearest_corner(box, (5, 3)), (0, 0))
        self.assertEqual(geo.nearest_corner(box, (35, 3)), (40, 0))
        self.assertEqual(geo.nearest_corner(box, (35, 17)), (40, 20))
        self.assertEqual(geo.nearest_corner(box, (5, 17)), (0, 20))
        # A tie takes the min side: a grab at the exact center → bottom-left.
        self.assertEqual(geo.nearest_corner(box, (20, 10)), (0, 0))
        # Outside the box still picks the nearest side.
        self.assertEqual(geo.nearest_corner(box, (99, -50)), (40, 0))


class TestHitAndBounds(unittest.TestCase):
    def test_rotated_rect_contains(self):
        item = rect(0, 0, 100, 10, 90)
        self.assertTrue(geo.contains(item, 0, 45))
        self.assertFalse(geo.contains(item, 45, 0))

    def test_thin_kinds_use_tolerance(self):
        line = {"kind": "line", "p1": (0, 0), "p2": (100, 0)}
        self.assertFalse(geo.contains(line, 50, 3))
        self.assertTrue(geo.contains(line, 50, 3, tol=5))
        point = {"kind": "point", "center": (10, 10)}
        self.assertTrue(geo.contains(point, 12, 10, tol=5))
        path = {"kind": "track", "points": ((0, 0), (10, 0), (10, 10)), "closed": False}
        self.assertFalse(geo.contains(path, 5, 5, tol=1))
        self.assertTrue(geo.contains({**path, "closed": True}, 5, 5, tol=1))

    def test_smooth_track_is_hit_on_its_curve(self):
        """A smooth track is hit where it is drawn — the curve Scena samples —
        not on the straight segments between its points."""
        straight = {"kind": "track", "points": ((0, 0), (100, 0), (100, 100), (0, 100)),
                    "closed": False, "smooth": 0.0}
        smooth = {**straight, "smooth": 1.0}
        curve = geo.track_curve(smooth)
        self.assertGreater(len(curve), len(smooth["points"]))
        for p in smooth["points"]:                      # it runs through its points
            self.assertTrue(any(math.dist(p, c) < 1e-6 for c in curve), p)
        # The sample farthest from the straight segments: off them, on the curve.
        far = max(curve, key=lambda c: min(geo._dist_to_segment(c, a, b) for a, b in
                                           zip(straight["points"], straight["points"][1:])))
        self.assertTrue(geo.contains(smooth, *far, tol=1))
        self.assertFalse(geo.contains(straight, *far, tol=1))
        # Bounds stay the points' box (LevelItem.center reads the same).
        self.assertEqual(geo.aabb(smooth), geo.aabb(straight))

    def test_regular_polygon_vertices_and_hit(self):
        hexagon = {"kind": "regular_polygon", "center": (0, 0), "radius": 10, "n": 6,
                   "angle": 0}
        v = geo.regular_vertices(hexagon)
        self.assertEqual(len(v), 6)
        self.assertAlmostEqual(v[0][0], 10)                  # vertex 0 toward angle
        self.assertAlmostEqual(v[1][1], 10 * math.sin(math.radians(60)))   # counter-clockwise
        self.assertTrue(geo.contains(hexagon, 0, 0))
        self.assertTrue(geo.contains(hexagon, 9.9, 0, tol=0.5))
        self.assertFalse(geo.contains(hexagon, 0, 9.5))      # past the flat top edge (8.66)
        x0, y0, x1, y1 = geo.aabb(hexagon)
        self.assertAlmostEqual(x1 - x0, 20)
        self.assertAlmostEqual(y1 - y0, 2 * 10 * math.sin(math.radians(60)))
        self.assertEqual(geo.translate(hexagon, 5, 1), {"center": (5, 1)})

    def test_polygon_inside_and_edge(self):
        poly = {"kind": "polygon", "points": ((0, 0), (10, 0), (5, 10))}
        self.assertTrue(geo.contains(poly, 5, 3))
        self.assertFalse(geo.contains(poly, 0, 9))

    def test_ellipse(self):
        e = rect(0, 0, 20, 10, 0, kind="ellipse")
        self.assertTrue(geo.contains(e, 9, 0))
        self.assertFalse(geo.contains(e, 9, 4))

    @given(cx=_coord, cy=_coord, w=_extent, h=_extent, r=_angle)
    def test_aabb_holds_every_corner(self, cx, cy, w, h, r):
        item = rect(cx, cy, w, h, r)
        x0, y0, x1, y1 = geo.aabb(item)
        for x, y in geo.corners(item):
            self.assertTrue(x0 - 1e-9 <= x <= x1 + 1e-9 and y0 - 1e-9 <= y <= y1 + 1e-9)

    def test_inside_box(self):
        item = rect(10, 10, 4, 4)
        self.assertTrue(geo.inside(item, (0, 0, 20, 20)))
        self.assertFalse(geo.inside(item, (9, 9, 20, 20)))


class TestHandles(unittest.TestCase):
    def test_counts_per_kind(self):
        self.assertEqual(len(geo.handles(rect(), 10)), 9)
        self.assertEqual(len(geo.handles(rect(kind="image"), 10)), 5)   # corners + rotate
        self.assertEqual(len(geo.handles({"kind": "circle", "center": (0, 0), "radius": 5}, 10)), 1)
        self.assertEqual(len(geo.handles({"kind": "line", "p1": (0, 0), "p2": (1, 1)}, 10)), 2)
        self.assertEqual(len(geo.handles({"kind": "point", "center": (0, 0)}, 10)), 0)

    def test_rotate_knob_is_above_the_top_edge(self):
        h = [x for x in geo.handles(rect(0, 0, 100, 40, 90), 10) if x.role == "rotate"][0]
        self.assertTrue(close((h.x, h.y), (-30, 0)))

    @given(r=_angle, signs=_signs)
    def test_resize_cursor_is_a_known_name(self, r, signs):
        self.assertIn(geo.resize_cursor(rect(r=r), signs), ("ew", "ns", "nesw", "nwse"))

    def test_resize_cursor_follows_rotation(self):
        self.assertEqual(geo.resize_cursor(rect(r=0), (1, 0)), "ew")
        self.assertEqual(geo.resize_cursor(rect(r=90), (1, 0)), "ns")


if __name__ == "__main__":
    unittest.main()


# -- a group selection: rotate and scale together ---------------------------------

_pt = hst.tuples(_coord, _coord)


def _item(kind, c, size, r, pts):
    if kind in ("rect", "ellipse", "image"):
        item = {"kind": kind, "center": c, "width": size, "height": size / 2 + 1, "angle": r}
        if kind == "image":
            item["file"] = "a.png"
        return item
    if kind == "circle":
        return {"kind": kind, "center": c, "radius": size}
    if kind == "regular_polygon":
        return {"kind": kind, "center": c, "radius": size, "n": 5, "angle": r}
    if kind == "triangle":
        return {"kind": kind, "center": c, "radius": size, "angle": r, "base_ratio": 0.6}
    if kind == "line":
        return {"kind": kind, "p1": pts[0], "p2": pts[1]}
    if kind in ("polygon", "track"):
        return {"kind": kind, "points": tuple(pts)}
    return {"kind": "point", "center": c}


_items = hst.builds(_item, hst.sampled_from(("rect", "ellipse", "image", "circle", "regular_polygon",
                                             "triangle", "line", "polygon", "track", "point")),
                    _pt, _extent, _angle, hst.lists(_pt, min_size=3, max_size=5))


def _refs(item):
    """The places a group transform moves: ends, points, or the center."""
    if item["kind"] == "line":
        return [item["p1"], item["p2"]]
    if item["kind"] in ("polygon", "track"):
        return list(item["points"])
    return [item["center"]]


def _turned(p, origin, deg):
    dx, dy = geo.rot(p[0] - origin[0], p[1] - origin[1], deg)
    return origin[0] + dx, origin[1] + dy


class TestGroupTransform(unittest.TestCase):
    @given(item=_items, origin=_pt, deg=_angle)
    def test_rotate_turns_places_and_angle_and_keeps_the_kind(self, item, origin, deg):
        new = {**item, **geo.rotate_item(item, origin, deg)}
        self.assertEqual(set(new), set(item))
        for a, b in zip(_refs(item), _refs(new)):
            self.assertTrue(close(_turned(a, origin, deg), b, 1e-6))
        if "angle" in item:
            d = (new["angle"] - item["angle"] - deg) % 360.0
            self.assertTrue(min(d, 360.0 - d) < 1e-6)
        for k in ("width", "height", "radius", "n"):
            if k in item:
                self.assertEqual(new[k], item[k])

    @given(item=_items, origin=_pt, deg=_angle)
    def test_rotate_there_and_back_is_the_identity(self, item, origin, deg):
        there = {**item, **geo.rotate_item(item, origin, deg)}
        back = {**there, **geo.rotate_item(there, origin, -deg)}
        for a, b in zip(_refs(item), _refs(back)):
            self.assertTrue(close(a, b, 1e-6))

    @given(item=_items, origin=_pt, s=hst.floats(0.1, 10))
    def test_scale_moves_places_and_sizes_evenly(self, item, origin, s):
        new = {**item, **geo.scale_item(item, origin, s)}
        self.assertEqual(set(new), set(item))
        for a, b in zip(_refs(item), _refs(new)):
            want = (origin[0] + (a[0] - origin[0]) * s, origin[1] + (a[1] - origin[1]) * s)
            self.assertTrue(close(want, b, 1e-6))
        for k in ("width", "height", "radius"):
            if k in item:
                self.assertAlmostEqual(new[k], item[k] * s, places=6)
        if "angle" in item:
            self.assertEqual(new["angle"], item["angle"])
        back = {**new, **geo.scale_item(new, origin, 1 / s)}
        for a, b in zip(_refs(item), _refs(back)):
            self.assertTrue(close(a, b, 1e-6))

    @given(items=hst.lists(_items, min_size=2, max_size=4),
           signs=hst.sampled_from(geo.CORNER_SIGNS), p=_pt,
           grid=hst.sampled_from([0.0, 10.0]))
    def test_group_scale_keeps_the_anchor_and_scales_the_box(self, items, signs, p, grid):
        box = geo.union_aabb(items)
        assume(box[2] - box[0] > 1 and box[3] - box[1] > 1)
        s, anchor = geo.group_scale(box, signs, p, grid)
        self.assertGreaterEqual(s, geo.MIN_SCALE)
        new = [{**it, **geo.scale_item(it, anchor, s)} for it in items]
        nb = geo.union_aabb(new)
        want = (anchor[0] + (box[0] - anchor[0]) * s, anchor[1] + (box[1] - anchor[1]) * s,
                anchor[0] + (box[2] - anchor[0]) * s, anchor[1] + (box[3] - anchor[1]) * s)
        self.assertTrue(close(nb, want, 1e-6 * max(1.0, s) * 1000), (nb, want))

    def test_group_scale_puts_the_dragged_corner_on_the_grid(self):
        box = (0.0, 0.0, 100.0, 50.0)
        s, anchor = geo.group_scale(box, (1, 1), (203.0, 60.0), 10.0)
        self.assertEqual(anchor, (0.0, 0.0))
        self.assertAlmostEqual(s, 2.0)            # x stretches most: the corner's x is 200
        s, anchor = geo.group_scale(box, (-1, -1), (-12.0, -40.0), 10.0)
        self.assertEqual(anchor, (100.0, 50.0))
        self.assertAlmostEqual(s, 1.8)            # y: 50 − (−40) = 90 = 1.8 × 50

    def test_group_scale_never_mirrors(self):
        s, _ = geo.group_scale((0.0, 0.0, 100.0, 100.0), (1, 1), (-50.0, -50.0), 0.0)
        self.assertEqual(s, geo.MIN_SCALE)

    def test_a_row_of_points_scales_on_its_one_axis(self):
        s, anchor = geo.group_scale((0.0, 5.0, 100.0, 5.0), (1, 1), (150.0, 900.0), 0.0)
        self.assertAlmostEqual(s, 1.5)

    def test_group_handles_are_the_corners_and_a_knob_above(self):
        hs = geo.group_handles((10.0, 20.0, 100.0, 40.0, 0.0), 5.0)
        corners = {(h.x, h.y) for h in hs if h.role == "group_resize"}
        self.assertEqual(corners, {(-40.0, 0.0), (60.0, 0.0), (60.0, 40.0), (-40.0, 40.0)})
        knob = [h for h in hs if h.role == "group_rotate"]
        self.assertEqual(len(knob), 1)
        self.assertTrue(close((knob[0].x, knob[0].y), (10.0, 45.0)))


class TestPack(unittest.TestCase):
    @given(items=hst.lists(_items, min_size=2, max_size=6), axis=hst.sampled_from("xy"))
    def test_boxes_touch_in_order_from_the_first_and_keep_the_other_axis(self, items, axis):
        items = [{**it, "id": k + 1} for k, it in enumerate(items)]
        i = 0 if axis == "x" else 1
        shifts = geo.pack(items, axis)
        before = [geo.aabb(it) for it in items]
        order = sorted(range(len(items)), key=lambda k: (before[k][i], before[k][1 - i], k))
        after = [geo.aabb({**items[k], **geo.translate(items[k], *shifts[items[k]["id"]])})
                 for k in order]
        self.assertTrue(close(after[0], before[order[0]], 1e-9))     # the first stays
        for prev, nxt in zip(after, after[1:]):
            # Gap 0, never an overlap: the near edge sits on the previous far edge.
            self.assertAlmostEqual(nxt[i], prev[i + 2], places=6)
        for it in items:
            self.assertEqual(shifts[it["id"]][1 - i], 0.0)        # other axis kept

    def test_a_row_keeps_the_leftmost_and_butts_the_rest(self):
        items = [{"id": 1, "kind": "rect", "center": (500, 10), "width": 20, "height": 20},
                 {"id": 2, "kind": "rect", "center": (100, 50), "width": 40, "height": 10},
                 {"id": 3, "kind": "circle", "center": (300, 0), "radius": 5}]
        self.assertEqual(geo.pack(items, "x"), {2: (0.0, 0.0), 3: (-175.0, 0.0),
                                               1: (-360.0, 0.0)})

    def test_a_column_goes_up_from_the_lowest(self):
        items = [{"id": 1, "kind": "point", "center": (0, 90)},
                 {"id": 2, "kind": "rect", "center": (0, 10), "width": 5, "height": 20}]
        self.assertEqual(geo.pack(items, "y"), {2: (0.0, 0.0), 1: (0.0, -70.0)})
