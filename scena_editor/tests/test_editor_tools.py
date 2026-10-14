"""Editor controller headless: tools, selection, gestures, undo, files.

Pointer events are world coordinates (y up), as the host passes them. A fake
viewport stands in for Scena's camera.

Run: python -m unittest scena_editor.tests.test_editor_tools
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import given, settings, strategies as hst  # noqa: E402

from scena.level_format import parse  # noqa: E402
from scena_editor import geometry as geo  # noqa: E402
from scena_editor.doc import LevelDoc  # noqa: E402
from scena_editor.i18n import t  # noqa: E402
from scena_editor.tools import ALT_LABEL, MIDDLE, PRIMARY, Editor, key_label  # noqa: E402


class FakeViewport:
    """Camera: ``look`` (world point at the view center) + ``zoom``.
    ``pan_by`` moves the content, like ``canvas.pan_by``."""

    def __init__(self, zoom=1.0, look=(0.0, 0.0)):
        self.zoom = zoom
        self.look = list(look)
        self.fitted = None
        self.reset_to = None

    def pan_by(self, dx, dy):
        self.look[0] -= dx
        self.look[1] -= dy

    def zoom_about(self, factor, x, y):
        # keep (x, y) where it is on screen
        sx, sy = self.to_screen(x, y)
        self.zoom *= factor
        wx, wy = self.to_world(sx, sy)
        self.look[0] += x - wx
        self.look[1] += y - wy

    def fit(self, box):
        self.fitted = box

    def actual_size(self):
        self.zoom = 1.0

    def to_world(self, sx, sy):
        return self.look[0] + sx / self.zoom, self.look[1] + sy / self.zoom

    def to_screen(self, x, y):
        return (x - self.look[0]) * self.zoom, (y - self.look[1]) * self.zoom


def ed(zoom=1.0):
    e = Editor(LevelDoc((1000, 800)), FakeViewport(zoom))
    return e


def drag(e, a, b, steps=4, button=0, shift=False, space=False):
    e.pointer_down(*a, button, shift=shift, space=space)
    for i in range(1, steps + 1):
        e.pointer_move(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps,
                       shift=shift)
    e.pointer_up(*b, button, shift=shift)


def click(e, p, shift=False):
    e.pointer_down(*p, shift=shift)
    e.pointer_up(*p, shift=shift)


class TestCreate(unittest.TestCase):
    def test_rect_by_drag_snaps_corners(self):
        e = ed()
        e.set_tool("rect")
        drag(e, (11, 19), (98, 51))
        item = e.single()
        self.assertEqual(item["kind"], "rect")
        self.assertEqual(geo.aabb(item), (10, 20, 100, 50))
        self.assertEqual(e.tool, "select")
        self.assertTrue(e.history.can_undo)

    def test_shift_draws_without_snap(self):
        e = ed()
        e.set_tool("ellipse")
        drag(e, (11, 19), (98, 51), shift=True)
        self.assertEqual(geo.aabb(e.single()), (11, 19, 98, 51))

    def test_circle_and_line(self):
        e = ed()
        e.set_tool("circle")
        drag(e, (100, 100), (130, 140))
        self.assertEqual(e.single()["radius"], 50.0)
        e.set_tool("line")
        drag(e, (0, 0), (52, 0))
        self.assertEqual((e.single()["p1"], e.single()["p2"]), ((0, 0), (50, 0)))

    def test_click_makes_a_default_shape(self):
        """A click (no drag) with a shape tool makes a DEFAULT_SIZE shape at the
        snapped click — rect / ellipse top-left there, circle centered, line to
        the right — one undo step, then back to Select with it selected."""
        want = {
            "rect": {"center": (60, 160), "width": 100, "height": 100},
            "ellipse": {"center": (60, 160), "width": 100, "height": 100},
            "circle": {"center": (10, 210), "radius": 50},
            "line": {"p1": (10, 210), "p2": (110, 210)},
        }
        for tool, fields in want.items():
            with self.subTest(tool=tool):
                e = ed()
                e.set_tool(tool)
                click(e, (12, 208))
                item = e.single()
                self.assertEqual(item["kind"], tool)
                for key, value in fields.items():
                    self.assertEqual(item[key], value, key)
                self.assertEqual(e.tool, "select")
                self.assertEqual(e.selection, [item["id"]])
                self.assertTrue(e.undo())
                self.assertEqual(e.doc.items, [])
                self.assertFalse(e.history.can_undo)

    def test_regular_polygon_click_and_drag(self):
        """A click: a hexagon of radius 50 centered on the snapped click, a
        vertex on top. A drag from the center out sets the radius (snapped)."""
        e = ed()
        e.set_tool("regular_polygon")
        click(e, (12, 208))
        item = e.single()
        self.assertEqual((item["kind"], item["center"], item["radius"], item["n"],
                          item["angle"]), ("regular_polygon", (10, 210), 50, 6, 90))
        self.assertEqual(e.tool, "select")
        e.set_tool("regular_polygon")
        drag(e, (300, 300), (300, 337))
        self.assertEqual((e.single()["center"], e.single()["radius"]), ((300, 300), 40))
        e.set_tool("regular_polygon")
        drag(e, (500, 500), (503, 503))                    # a drag (> 3 px) to radius 0: dropped
        self.assertEqual(len(e.doc.items), 2)

    def test_regular_polygon_handles_resize_and_turn(self):
        e = ed()
        a = e.doc.add({"kind": "regular_polygon", "center": (100, 100), "radius": 50, "n": 5,
                       "angle": 90})
        e.history.commit()
        e.selection = [a]
        radius, knob = geo.handles(e.doc.get(a), 20)
        self.assertEqual(radius.role, "radius")
        self.assertAlmostEqual(radius.x, 100)
        self.assertAlmostEqual(radius.y, 150)               # vertex 0, on top
        self.assertEqual(knob.role, "rotate")
        self.assertAlmostEqual(knob.y, 170)                 # further out on the spoke
        drag(e, (radius.x, radius.y), (100, 172))
        self.assertEqual(e.doc.get(a)["radius"], 70)
        radius, knob = geo.handles(e.doc.get(a), 20)
        drag(e, (knob.x, knob.y), (190, 100 + 3))           # toward +x: angle ~0, snaps 15°
        self.assertEqual(e.doc.get(a)["angle"], 0)
        self.assertEqual(e.doc.get(a)["n"], 5)

    def test_default_shape_corners_land_on_every_grid(self):
        """DEFAULT_SIZE is a multiple of every grid step: all corners snap."""
        from scena_editor.tools import DEFAULT_SIZE, GRID_SIZES
        for grid in GRID_SIZES:
            self.assertEqual(DEFAULT_SIZE % grid, 0, grid)
        e = ed()
        e.grid = 20.0
        e.set_tool("rect")
        click(e, (47, 93))
        x0, y0, x1, y1 = geo.aabb(e.single())
        self.assertEqual([v % 20 for v in (x0, y0, x1, y1)], [0, 0, 0, 0])

    def test_shift_click_default_is_unsnapped(self):
        e = ed()
        e.set_tool("rect")
        click(e, (12, 208), shift=True)
        self.assertEqual(e.single()["center"], (62, 158))

    def test_tool_keys(self):
        """P → Point (used most), A → Path, G → Polygon; T is free. Every key
        names a tool, every tool has one key."""
        from scena_editor.tools import KEY_OF, TOOL_KEYS, TOOLS
        self.assertEqual(sorted(TOOL_KEYS.values()), sorted(TOOLS))
        self.assertEqual(len(KEY_OF), len(TOOL_KEYS))
        for key, tool in (("P", "point"), ("A", "track"), ("G", "polygon"), ("V", "select"),
                          ("H", "hand")):
            e = ed()
            self.assertTrue(e.key(key))
            self.assertEqual(e.tool, tool)
        e = ed()
        self.assertFalse(e.key("T"))
        self.assertEqual(e.tool, "select")

    def test_flat_drag_is_discarded(self):
        e = ed()
        e.set_tool("rect")
        drag(e, (10, 10), (60, 12))   # snaps to zero height
        self.assertEqual(e.doc.items, [])
        self.assertFalse(e.history.can_undo)

    def test_point_click(self):
        e = ed()
        e.set_tool("point")
        click(e, (33, 47))
        self.assertEqual(e.single()["center"], (30, 50))

    def test_polygon_enter_and_double_click(self):
        e = ed()
        e.set_tool("polygon")
        for p in ((0, 0), (100, 0), (50, 80)):
            click(e, p)
        e.key("ENTER")
        self.assertEqual(e.single()["kind"], "polygon")
        self.assertEqual(len(e.single()["points"]), 3)
        e.set_tool("track")
        for p in ((0, 0), (100, 0)):
            click(e, p)
        click(e, (100, 0))           # the second press of a double click
        e.double_click(100, 0)
        self.assertEqual(e.single()["points"], ((0, 0), (100, 0)))

    def test_too_few_points_and_esc(self):
        e = ed()
        e.set_tool("polygon")
        click(e, (0, 0))
        click(e, (10, 0))
        self.assertFalse(e.finish_points())
        self.assertEqual(e.doc.items, [])
        e.set_tool("track")
        click(e, (0, 0))
        e.key("ESC")
        self.assertEqual(e.pending, [])

    def test_image_request_and_add(self):
        e = ed()
        e.set_tool("image")
        self.assertTrue(e.image_requested)
        e.add_image("/abs/fundo.png", (64, 32), (500, 400))
        item = e.single()
        self.assertEqual((item["width"], item["height"]), (64, 32))
        self.assertFalse(e.image_requested)


class TestSelectAndMove(unittest.TestCase):
    def setUp(self):
        self.e = ed()
        self.a = self.e.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        self.b = self.e.doc.add({"kind": "rect", "center": (300, 100), "width": 40, "height": 20})
        self.e.history.commit()

    def test_click_selects_and_empty_click_clears(self):
        click(self.e, (100, 100))
        self.assertEqual(self.e.selection, [self.a])
        click(self.e, (700, 700))
        self.assertEqual(self.e.selection, [])

    def test_shift_click_toggles(self):
        click(self.e, (100, 100))
        click(self.e, (300, 100), shift=True)
        self.assertEqual(self.e.selection, [self.a, self.b])
        click(self.e, (100, 100), shift=True)
        self.assertEqual(self.e.selection, [self.b])

    def test_drag_at_the_center_snaps_bottom_left(self):
        drag(self.e, (100, 100), (133, 104))
        item = self.e.doc.get(self.a)
        x0, y0, _x1, _y1 = geo.aabb(item)
        self.assertEqual((x0 % 10, y0 % 10), (0, 0))
        self.assertEqual(item["center"], (130, 100))
        self.assertTrue(self.e.history.can_undo)

    def test_drag_snaps_the_grabbed_corner(self):
        """Moving snaps the corner of the selection's box nearest the press
        (off-grid 137 × 83 shape: only that corner can land on the grid). The
        grabs sit inside the box, clear of the corner and edge handles."""
        e = ed()
        a = e.doc.add({"kind": "rect", "center": (203.5, 201.5), "width": 137, "height": 83})
        e.history.commit()                  # box 135..272 × 160..243
        for grab, corner in (((250, 225), (2, 3)), ((155, 175), (0, 1)),
                             ((155, 225), (0, 3)), ((250, 175), (2, 1))):
            with self.subTest(grab=grab):
                before = dict(e.doc.get(a))
                drag(e, grab, (grab[0] + 41, grab[1] - 17))
                box = geo.aabb(e.doc.get(a))
                self.assertEqual((box[corner[0]] % 10, box[corner[1]] % 10), (0, 0), box)
                e.undo()
                self.assertEqual(e.doc.get(a), before)

    def test_multi_selection_snaps_the_union_corner(self):
        click(self.e, (100, 100))
        click(self.e, (300, 100), shift=True)
        self.e.doc.update(self.b, center=(303, 104))     # union box: 80..323 × 90..114
        drag(self.e, (310, 108), (337, 121))             # nearest corner: top-right
        x0, y0, x1, y1 = geo.union_aabb([self.e.doc.get(self.a), self.e.doc.get(self.b)])
        self.assertEqual((x1 % 10, y1 % 10), (0, 0))

    def test_shift_drag_moves_free(self):
        click(self.e, (100, 100))
        drag(self.e, (100, 100), (133, 104), shift=True)
        self.assertEqual(self.e.doc.get(self.a)["center"], (133, 104))

    def test_drag_moves_every_selected(self):
        click(self.e, (100, 100))
        click(self.e, (300, 100), shift=True)
        drag(self.e, (300, 100), (300, 150))
        self.assertEqual(self.e.doc.get(self.a)["center"], (100, 150))
        self.assertEqual(self.e.doc.get(self.b)["center"], (300, 150))

    def test_locked_items_select_but_do_not_move(self):
        self.e.doc.update(self.a, locked=True)
        drag(self.e, (100, 100), (200, 200))
        self.assertEqual(self.e.selection, [self.a])
        self.assertEqual(self.e.doc.get(self.a)["center"], (100, 100))
        self.assertEqual(self.e.handles(), [])

    def test_rubber_band_and_shift_adds(self):
        drag(self.e, (0, 0), (200, 200), shift=True)
        self.assertEqual(self.e.selection, [self.a])
        drag(self.e, (250, 0), (400, 200), shift=True)
        self.assertEqual(self.e.selection, [self.a, self.b])
        self.assertIsNone(self.e.band)

    def test_empty_drag_box_selects_and_replaces(self):
        click(self.e, (300, 100))
        drag(self.e, (0, 0), (200, 200))
        self.assertEqual(self.e.selection, [self.a])
        self.assertEqual(self.e.viewport.look, [0.0, 0.0])      # no pan

    def test_hand_tool_pans_and_keeps_the_grabbed_point(self):
        e, vp = self.e, self.e.viewport
        e.set_tool("hand")
        vp.zoom = 0.5
        grab_screen = (40.0, -30.0)
        grab = vp.to_world(*grab_screen)
        e.pointer_down(*grab)
        for i in range(1, 6):
            screen = (40.0 + 25 * i, -30.0 + 10 * i)
            e.pointer_move(*vp.to_world(*screen))       # fresh world point per event
            under = vp.to_world(*screen)
            self.assertAlmostEqual(under[0], grab[0])
            self.assertAlmostEqual(under[1], grab[1])
        e.pointer_up(*vp.to_world(*screen))
        self.assertEqual(e.selection, [])

    def test_middle_and_space_pan_even_over_items(self):
        vp = self.e.viewport
        drag(self.e, (100, 100), (150, 100), button=MIDDLE)
        self.assertEqual(self.e.doc.get(self.a)["center"], (100, 100))
        self.assertNotEqual(vp.look, [0.0, 0.0])

    def test_click_again_cycles_through_overlaps(self):
        c = self.e.doc.add({"kind": "rect", "center": (100, 100), "width": 10, "height": 10})
        click(self.e, (100, 100))
        self.assertEqual(self.e.selection, [c])          # topmost
        click(self.e, (100, 100))
        self.assertEqual(self.e.selection, [self.a])     # the one under it

    def test_nudge_delete_duplicate_restack(self):
        click(self.e, (100, 100))
        self.e.key("RIGHT")
        self.assertEqual(self.e.doc.get(self.a)["center"], (101, 100))
        self.e.key("UP", shift=True)
        self.assertEqual(self.e.doc.get(self.a)["center"], (101, 110))
        self.e.duplicate()
        self.assertEqual(len(self.e.doc.items), 3)
        copy = self.e.single()
        self.e.restack(front=False)
        self.assertEqual(self.e.doc.items[0]["id"], copy["id"])
        self.e.delete()
        self.assertEqual(len(self.e.doc.items), 2)


class TestHandles(unittest.TestCase):
    def test_resize_corner_keeps_opposite_corner(self):
        e = ed()
        a = e.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        e.selection = [a]
        drag(e, (120, 110), (150, 140))               # top-right handle
        self.assertEqual(geo.aabb(e.doc.get(a)), (80, 90, 150, 140))

    def test_rotate_snaps_to_15(self):
        e = ed()
        a = e.doc.add({"kind": "rect", "center": (0, 0), "width": 40, "height": 20})
        e.selection = [a]
        knob = [h for h in e.handles() if h.role == "rotate"][0]
        drag(e, (knob.x, knob.y), (-50, 47))
        self.assertEqual(e.doc.get(a)["angle"] % 15, 0)

    def test_circle_radius_line_end_vertex(self):
        e = ed()
        c = e.doc.add({"kind": "circle", "center": (0, 0), "radius": 10})
        e.selection = [c]
        drag(e, (10, 0), (33, 0))
        self.assertEqual(e.doc.get(c)["radius"], 30)
        p = e.doc.add({"kind": "polygon", "points": [(0, 0), (100, 0), (50, 80)]})
        e.selection = [p]
        drag(e, (50, 80), (52, 99))
        self.assertEqual(e.doc.get(p)["points"][2], (50, 100))


class TestGroupHandles(unittest.TestCase):
    def _two(self, e):
        a = e.doc.add({"kind": "rect", "center": (50, 50), "width": 100, "height": 100})
        b = e.doc.add({"kind": "circle", "center": (200, 50), "radius": 50})
        e.history.reset(e.doc)
        e.selection = [a, b]
        return a, b

    def _handle(self, e, role, key=None):
        return next(h for h in e.handles() if h.role == role and (key is None or h.key == key))

    def test_several_selected_show_corners_and_a_knob_around_what_moves(self):
        e = ed()
        a, b = self._two(e)
        roles = sorted(h.role for h in e.handles())
        self.assertEqual(roles, ["group_resize"] * 4 + ["group_rotate"])
        self.assertEqual(e.group_frame(), (125.0, 50.0, 250.0, 100.0, 0.0))
        c = e.doc.add({"kind": "point", "center": (900, 900), "locked": True})
        e.selection = [a, b, c]                  # a locked item is not in the box
        self.assertEqual(e.group_frame(), (125.0, 50.0, 250.0, 100.0, 0.0))
        e.selection = [a]
        self.assertIsNone(e.group_frame())
        self.assertTrue(all(not h.role.startswith("group_") for h in e.handles()))
        p = e.doc.add({"kind": "point", "center": (5, 5)})
        q = e.doc.add({"kind": "point", "center": (5, 5)})
        e.selection = [p, q]                     # a box that is one point: no handles
        self.assertEqual(e.handles(), [])

    def test_corner_drag_scales_evenly_and_lands_the_corner_on_the_grid(self):
        e = ed()
        a, b = self._two(e)
        h = self._handle(e, "group_resize", (1, 1))       # top-right: (250, 100)
        self.assertEqual(e.cursor(h.x, h.y), "nesw")
        drag(e, (h.x, h.y), (497, 130))                   # x stretches most: 500 = 2 ×
        self.assertEqual(e.doc.get(a)["center"], (100, 100))
        self.assertEqual((e.doc.get(a)["width"], e.doc.get(a)["height"]), (200, 200))
        self.assertEqual(e.doc.get(b)["center"], (400, 100))
        self.assertEqual(e.doc.get(b)["radius"], 100)
        self.assertEqual(e.doc.get(b)["kind"], "circle")
        self.assertTrue(e.undo())                         # one step
        self.assertEqual(e.doc.get(a)["width"], 100)
        self.assertFalse(e.history.can_undo)

    def test_shift_scales_without_snap_and_past_the_anchor_does_not_mirror(self):
        e = ed()
        a, b = self._two(e)
        h = self._handle(e, "group_resize", (1, 1))
        drag(e, (h.x, h.y), (378, 77), shift=True)        # 378 / 250 = 1.512
        self.assertAlmostEqual(e.doc.get(a)["width"], 151.2, places=2)
        e.undo()
        h = self._handle(e, "group_resize", (1, 1))
        drag(e, (h.x, h.y), (-300, -300))
        self.assertGreater(e.doc.get(a)["width"], 0)
        self.assertGreaterEqual(e.doc.get(a)["center"][0], 0)   # stays right of the anchor

    def test_knob_turns_the_group_about_its_center_in_15_degree_steps(self):
        e = ed()
        a, b = self._two(e)
        h = self._handle(e, "group_rotate")
        self.assertEqual(e.cursor(h.x, h.y), "rotate")
        cx, cy = 125.0, 50.0
        # Pointer just above straight left of the center: 88°, snapped to 90°.
        e.pointer_down(h.x, h.y)
        e.pointer_move(cx - 100, cy + 3.5)
        self.assertEqual(e.group_frame()[4], 90.0)       # the frame turns with it
        self.assertEqual(e.cursor(cx - 100, cy), "rotate")
        e.pointer_up(cx - 100, cy + 3.5)
        self.assertEqual(e.doc.get(a)["angle"], 90)
        self.assertEqual(e.doc.get(a)["center"], (125, -25))
        self.assertEqual(e.doc.get(b)["center"], (125, 125))
        self.assertEqual(e.group_frame()[4], 0.0)        # then a new upright box
        self.assertTrue(e.undo())
        self.assertEqual(e.doc.get(a)["center"], (50, 50))

    def test_shift_turns_freely_and_esc_puts_everything_back(self):
        e = ed()
        a, b = self._two(e)
        h = self._handle(e, "group_rotate")
        cx, cy = 125.0, 50.0
        e.pointer_down(h.x, h.y, shift=True)
        e.pointer_move(cx - 100, cy + 3.5, shift=True)
        self.assertAlmostEqual(e.doc.get(a)["angle"], 88.0, places=0)
        e.key("ESC")
        self.assertEqual(e.doc.get(a)["center"], (50, 50))
        self.assertEqual(e.doc.get(a)["angle"], 0)
        self.assertFalse(e.history.can_undo)

    def test_locked_items_stay_put(self):
        e = ed()
        a, b = self._two(e)
        c = e.doc.add({"kind": "rect", "center": (600, 600), "width": 10, "height": 10,
                       "locked": True})
        e.history.reset(e.doc)
        e.selection = [a, b, c]
        h = self._handle(e, "group_rotate")
        drag(e, (h.x, h.y), (25, 50))
        self.assertEqual(e.doc.get(c)["center"], (600, 600))
        self.assertEqual(e.doc.get(a)["angle"], 90)


class TestRowColumn(unittest.TestCase):
    def test_row_and_column_are_one_step_and_skip_locked(self):
        e = ed()
        a = e.doc.add({"kind": "rect", "center": (10, 10), "width": 20, "height": 20})
        b = e.doc.add({"kind": "rect", "center": (100, 40), "width": 20, "height": 20})
        c = e.doc.add({"kind": "rect", "center": (60, 400), "width": 20, "height": 20,
                       "locked": True})
        e.history.reset(e.doc)
        e.selection = [a, b, c]
        self.assertTrue(e.pack("x"))
        self.assertEqual(e.doc.get(b)["center"], (30, 40))       # a spans 0..20
        self.assertEqual(e.doc.get(c)["center"], (60, 400))      # locked: stays
        self.assertEqual(e.message, "Placed 2 items in a row")
        self.assertFalse(e.pack("x"))                            # already a row: no step
        self.assertTrue(e.pack("y"))
        self.assertEqual(e.doc.get(b)["center"], (30, 30))       # on top of a (y up)
        self.assertEqual(e.message, "Placed 2 items in a column")
        e.undo()
        e.undo()
        self.assertEqual(e.doc.get(b)["center"], (100, 40))
        self.assertFalse(e.history.can_undo)

    def test_needs_two_items_that_move(self):
        e = ed()
        a = e.doc.add({"kind": "point", "center": (0, 0)})
        b = e.doc.add({"kind": "point", "center": (50, 0), "locked": True})
        e.selection = [a, b]
        self.assertFalse(e.pack("x"))


class TestAltDragAndSelectGroup(unittest.TestCase):
    def test_alt_drag_moves_copies_and_leaves_the_originals(self):
        e = ed()
        a = e.doc.add({"kind": "rect", "name": "bloco", "center": (50, 50), "width": 20,
                       "height": 20})
        b = e.doc.add({"kind": "point", "center": (100, 50)})
        lock = e.doc.add({"kind": "point", "center": (300, 300), "locked": True})
        e.history.reset(e.doc)
        e.selection = [a, b, lock]
        e.pointer_down(50, 50, alt=True)
        for x in (60, 80, 100):
            e.pointer_move(x, 50)
        e.pointer_up(100, 50)
        self.assertEqual(len(e.doc.items), 5)               # two copies; not the locked one
        self.assertEqual(e.doc.get(a)["center"], (50, 50))
        self.assertEqual(e.doc.get(b)["center"], (100, 50))
        copies = [e.doc.get(i) for i in e.selection]
        self.assertEqual([c["center"] for c in copies], [(100, 50), (150, 50)])
        self.assertEqual(copies[0]["name"], "bloco_2")
        self.assertTrue(e.undo())                           # copy + move: one step
        self.assertEqual(len(e.doc.items), 3)
        self.assertFalse(e.history.can_undo)

    def test_primary_keeps_a_move_straight_and_the_copy_lined_up(self):
        e = ed()
        a = e.doc.add({"kind": "rect", "center": (50, 53), "width": 20, "height": 20})  # y off grid
        e.history.reset(e.doc)
        e.selection = [a]
        e.pointer_down(50, 53, alt=True)
        e.pointer_move(80, 58, straight=True)        # mostly right
        self.assertEqual(e.hint(), t("hint.move", primary=key_label(PRIMARY)))
        e.pointer_move(121, 64, straight=True)
        e.pointer_up(121, 64)
        copy = e.doc.get(e.selection[0])
        self.assertEqual(copy["center"][1], 53)        # exactly level with the original
        self.assertEqual(copy["center"][0] - 10, 110)   # its left edge snapped to the grid
        self.assertEqual(e.doc.get(a)["center"], (50, 53))

    def test_straight_follows_the_longer_axis_and_can_change_mid_drag(self):
        e = ed()
        a = e.doc.add({"kind": "point", "center": (100, 100)})
        e.selection = [a]
        e.pointer_down(100, 100, shift=True)          # no snap: the numbers are exact
        e.pointer_move(106, 140, shift=True, straight=True)
        self.assertEqual(e.doc.get(a)["center"], (100, 140))     # mostly up: x stays
        e.pointer_move(106, 140, shift=True, straight=False)     # let go mid-drag
        self.assertEqual(e.doc.get(a)["center"], (106, 140))
        e.pointer_move(150, 120, shift=True, straight=True)      # now mostly right
        self.assertEqual(e.doc.get(a)["center"], (150, 100))
        e.pointer_up(150, 120, shift=True)
        self.assertEqual(e.hint(), t("hint.select", alt=ALT_LABEL))   # the drag is over

    def test_alt_click_copies_nothing(self):
        e = ed()
        a = e.doc.add({"kind": "point", "center": (50, 50)})
        e.pointer_down(50, 50, alt=True)
        e.pointer_up(50, 50)
        self.assertEqual(len(e.doc.items), 1)
        self.assertEqual(e.selection, [a])

    def test_alt_drag_of_a_locked_item_copies_nothing(self):
        e = ed()
        e.doc.add({"kind": "rect", "center": (50, 50), "width": 20, "height": 20,
                   "locked": True})
        e.pointer_down(50, 50, alt=True)
        e.pointer_move(90, 50)
        e.pointer_up(90, 50)
        self.assertEqual(len(e.doc.items), 1)

    def test_select_group_picks_its_items_in_file_order(self):
        e = ed()
        a = e.doc.add({"kind": "point", "groups": ["robo"], "center": (0, 0)})
        e.doc.add({"kind": "point", "groups": ["chao"], "center": (5, 0)})
        c = e.doc.add({"kind": "point", "groups": ["chao", "robo"], "center": (9, 0)})
        e.select_group("robo")
        self.assertEqual(e.selection, [a, c])
        self.assertFalse(e.history.can_undo)

    def test_selected_group_is_computed_from_the_selection(self):
        e = ed()
        a = e.doc.add({"kind": "point", "groups": ["robo"], "center": (0, 0)})
        b = e.doc.add({"kind": "point", "groups": ["chao", "Bloco"], "center": (5, 0)})
        c = e.doc.add({"kind": "point", "groups": ["chao", "robo", "Bloco"], "center": (9, 0)})
        self.assertIsNone(e.selected_group())                 # nothing selected
        e.select_group("robo")
        self.assertEqual(e.selected_group(), "robo")
        e.selection = [a, c, b]                                # one more: no longer the group
        self.assertIsNone(e.selected_group())
        e.selection = [a]                                      # part of it: neither
        self.assertIsNone(e.selected_group())
        e.selection = [c, b]                                   # chao and Bloco: same items
        self.assertEqual(e.selected_group(), "Bloco")          # the first A–Z (any case)
        e.select_group("chao")                                 # picked: it wins the tie
        self.assertEqual(e.selected_group(), "chao")
        e.select_group("robo")
        e.selection = [c, b]                                   # the pick is not a match
        self.assertEqual(e.selected_group(), "Bloco")
        e.select_group(None)                                   # None selects nothing
        self.assertEqual(e.selection, [])
        e.selection = [c, b]
        e.set_groups("robo", [b])                              # the group changes under it
        self.assertIsNone(e.selected_group())


class TestToolsAndImages(unittest.TestCase):
    def test_choosing_select_clears_the_selection(self):
        e = ed()
        a = e.doc.add({"kind": "point", "center": (0, 0)})
        e.selection = [a]
        e.set_tool("select")
        self.assertEqual(e.selection, [])

    def test_drawing_ends_in_select_with_the_new_item_selected(self):
        e = ed()
        e.set_tool("rect")
        drag(e, (0, 0), (50, 50))
        self.assertEqual(e.tool, "select")
        self.assertEqual(len(e.selection), 1)

    def test_replace_image_keeps_center_angle_height(self):
        e = ed()
        a = e.doc.add({"kind": "image", "file": "a.png", "center": (5, 6), "width": 40,
                       "height": 20, "angle": 30})
        e.history.commit()
        self.assertTrue(e.replace_image(a, "b.png", (300, 100)))
        item = e.doc.get(a)
        self.assertEqual((item["file"], item["center"], item["angle"]), ("b.png", (5, 6), 30))
        self.assertEqual((item["width"], item["height"]), (60.0, 20.0))
        e.undo()
        self.assertEqual(e.doc.get(a)["file"], "a.png")

    def test_actual_size(self):
        e = ed(zoom=0.3)
        e.actual_size()
        self.assertEqual(e.viewport.zoom, 1.0)


class TestClipboardAndRounding(unittest.TestCase):
    def test_copy_paste_offsets_names_and_selects(self):
        e = ed()
        a = e.doc.add({"kind": "rect", "name": "chao", "groups": ["g"], "center": (100, 100),
                       "width": 40, "height": 20})
        e.selection = [a]
        self.assertIn("chao = Rect(", e.copy())
        first = e.paste()
        second = e.paste()
        self.assertEqual(e.doc.get(first[0])["center"], (110, 90))
        self.assertEqual(e.doc.get(second[0])["center"], (120, 80))
        self.assertEqual(e.doc.get(first[0])["name"], "chao_2")
        self.assertEqual(e.doc.get(first[0])["groups"], ("g",))
        self.assertEqual(e.selection, second)
        e.undo()
        self.assertFalse(e.doc.has(second[0]))

    def test_cut_and_paste_into_a_new_level(self):
        e = ed()
        a = e.doc.add({"kind": "point", "name": "inicio", "center": (5, 5)})
        e.selection = [a]
        e.cut()
        self.assertEqual(e.doc.items, [])
        e.set_doc(LevelDoc())
        new = e.paste()
        self.assertEqual(e.doc.get(new[0])["name"], "inicio")    # free in this level

    def test_line_end_fields(self):
        e = ed()
        a = e.doc.add({"kind": "line", "p1": (0, 0), "p2": (10, 0)})
        e.selection = [a]
        self.assertTrue(e.set_field("x2", 30))
        self.assertTrue(e.set_field("y1", -5))
        self.assertEqual((e.doc.get(a)["p1"], e.doc.get(a)["p2"]), ((0, -5), (30, 0)))

    def test_editor_keeps_two_decimals(self):
        e = ed()
        a = e.doc.add({"kind": "rect", "center": (1 / 3, 2 / 3), "width": 239.99999999999994,
                       "height": 10, "angle": 30.000000001})
        item = e.doc.get(a)
        self.assertEqual((item["center"], item["width"], item["angle"]),
                         ((0.33, 0.67), 240.0, 30.0))
        e.selection = [a]
        drag(e, (0.33, 0.67), (17.123456, 3.987654), shift=True)
        cx, cy = e.doc.get(a)["center"]
        self.assertEqual((cx, cy), (round(cx, 2), round(cy, 2)))

    def test_files_and_code_have_no_float_noise(self):
        from scena.level_format import code_for, serialize
        item = {"kind": "rect", "name": None, "groups": (), "locked": False,
                "center": (866.9565217391305, 570.0), "width": 239.99999999999994,
                "height": 20.0, "angle": 0.0}
        self.assertIn("width=240,", code_for(item))
        out = serialize({"size": (100.0, 100.0), "items": [item]})["items"][0]
        self.assertEqual(out["width"], 240)
        self.assertEqual(out["center"], [866.956522, 570])


class TestUndo(unittest.TestCase):
    def test_one_step_per_gesture_and_exact_restore(self):
        e = ed()
        e.set_tool("rect")
        drag(e, (0, 0), (100, 50))
        after_create = e.doc.snapshot()
        drag(e, (50, 25), (90, 25), steps=10)     # many moves, one step
        e.undo()
        self.assertEqual(e.doc.snapshot(), after_create)
        e.undo()
        self.assertEqual(e.doc.items, [])
        self.assertFalse(e.history.can_undo)
        e.redo()
        e.redo()
        self.assertEqual(len(e.doc.items), 1)
        self.assertEqual(e.doc.items[0]["center"], (90, 25))

    def test_new_edit_clears_redo(self):
        e = ed()
        e.set_tool("point")
        click(e, (0, 0))
        e.undo()
        e.set_tool("point")
        click(e, (50, 50))
        self.assertFalse(e.redo())

    def test_selection_and_pan_are_not_steps(self):
        e = ed()
        e.doc.add({"kind": "point", "center": (0, 0)})
        e.history.commit()
        steps = len(e.history._past)
        click(e, (0, 0))
        drag(e, (500, 500), (600, 600))
        self.assertEqual(len(e.history._past), steps)

    def test_undo_back_to_saved_is_clean(self):
        e = ed()
        self.assertFalse(e.doc.dirty)
        e.set_tool("point")
        click(e, (0, 0))
        self.assertTrue(e.doc.dirty)
        e.undo()
        self.assertFalse(e.doc.dirty)

    def test_esc_cancels_a_drag(self):
        e = ed()
        a = e.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        e.history.commit()
        e.pointer_down(100, 100)
        e.pointer_move(200, 200)
        e.key("ESC")
        self.assertEqual(e.doc.get(a)["center"], (100, 100))


class TestPanel(unittest.TestCase):
    def test_fields_names_groups(self):
        e = ed()
        a = e.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        b = e.doc.add({"kind": "line", "p1": (0, 0), "p2": (10, 0)})
        e.selection = [a]
        self.assertTrue(e.set_field("name", "chao"))
        self.assertTrue(e.set_field("groups", "plataforma, especial, plataforma"))
        self.assertEqual(e.doc.get(a)["groups"], ("plataforma", "especial"))
        self.assertTrue(e.set_field("angle", 30))
        e.selection = [b]
        self.assertFalse(e.set_field("name", "chao"))
        self.assertIn("already used", e.message)
        self.assertTrue(e.set_field("x", 100))
        self.assertEqual(e.doc.get(b)["p1"], (95, 0))
        self.assertFalse(e.set_field("radius", 3))       # a line has no radius

    def test_groups_field_on_many_adds_and_removes_only_shared_groups(self):
        e = ed()
        a = e.doc.add({"kind": "point", "groups": ["robo", "chao"], "center": (0, 0)})
        b = e.doc.add({"kind": "point", "groups": ["robo", "agua"], "center": (5, 0)})
        e.selection = [a, b]
        # The field showed "robo" (both have it); chao / agua are partial.
        self.assertTrue(e.set_groups("robo, estrela"))
        self.assertEqual(e.doc.get(a)["groups"], ("robo", "chao", "estrela"))
        self.assertEqual(e.doc.get(b)["groups"], ("robo", "agua", "estrela"))
        self.assertEqual(e.message, 'Added "estrela" to 2 items')
        self.assertTrue(e.set_groups("estrela"))         # "robo" deleted from the field
        self.assertEqual(e.doc.get(a)["groups"], ("chao", "estrela"))
        self.assertEqual(e.doc.get(b)["groups"], ("agua", "estrela"))
        self.assertEqual(e.message, 'Removed "robo" from 2 items')
        e.undo()
        self.assertEqual(e.doc.get(a)["groups"], ("robo", "chao", "estrela"))

    def test_groups_field_on_many_counts_only_items_that_change(self):
        e = ed()
        a = e.doc.add({"kind": "point", "groups": ["x"], "center": (0, 0)})
        b = e.doc.add({"kind": "point", "center": (5, 0)})
        c = e.doc.add({"kind": "point", "center": (9, 0)})
        e.selection = [a, b, c]
        self.assertTrue(e.set_groups("x"))     # x was partial: added where missing
        self.assertEqual(e.message, 'Added "x" to 2 items')
        self.assertTrue(all(e.doc.get(i)["groups"] == ("x",) for i in (a, b, c)))

    def test_groups_field_with_no_change_is_no_step(self):
        e = ed()
        ids = [e.doc.add({"kind": "point", "groups": ["g"], "center": (i, 0)})
               for i in range(2)]
        e.history.reset(e.doc)                  # the items are the starting state
        e.selection = ids
        self.assertFalse(e.set_groups(" g ,g"))
        self.assertFalse(e.history.can_undo)
        self.assertFalse(e.set_field("groups", "g"))   # one item: same rule

    def test_groups_field_takes_semicolons_as_commas(self):
        # "," is the decimal separator in pt-BR, so ";" is the list one there.
        e = ed()
        a = e.doc.add({"kind": "point", "center": (0, 0)})
        e.selection = [a]
        self.assertTrue(e.set_field("groups", "chao; robo ;;estrela, chao"))
        self.assertEqual(e.doc.get(a)["groups"], ("chao", "robo", "estrela"))
        self.assertEqual(e.message, "Groups: chao, robo, estrela")

    def test_groups_field_on_one_item_says_the_groups_it_has(self):
        e = ed()
        a = e.doc.add({"kind": "point", "center": (0, 0)})
        e.selection = [a]
        self.assertTrue(e.set_field("groups", "chao, moving enemies"))
        # A name with a space is one group: the note shows it in « ».
        self.assertEqual(e.message, "Groups: chao, «moving enemies»")
        self.assertTrue(e.set_field("groups", ""))
        self.assertEqual(e.message, "No groups")

    def test_groups_field_hints_a_typo_of_an_existing_group(self):
        e = ed()
        e.doc.add({"kind": "point", "groups": ["plataforma"], "center": (0, 0)})
        a = e.doc.add({"kind": "point", "center": (5, 0)})
        e.selection = [a]
        self.assertTrue(e.set_field("groups", "plataform"))
        # The hint leads (a long note is cut at the status bar's end).
        self.assertTrue(e.message.startswith('"plataform" is a new group.'), e.message)
        self.assertIn("Did you mean 'plataforma'?", e.message)
        self.assertEqual(e.doc.get(a)["groups"], ("plataform",))   # a hint, not a refusal
        self.assertTrue(e.set_field("groups", "estrela"))           # nothing close: no hint
        self.assertNotIn("Did you mean", e.message)
        self.assertTrue(e.set_field("groups", "Plataforma"))        # case differs: hint
        self.assertIn("Did you mean 'plataforma'?", e.message)

    def test_selection_x_y_moves_the_box_center_and_skips_locked(self):
        e = ed()
        a = e.doc.add({"kind": "rect", "center": (10, 10), "width": 20, "height": 20})
        b = e.doc.add({"kind": "point", "center": (40, 30)})
        c = e.doc.add({"kind": "point", "center": (500, 500), "locked": True})
        e.history.reset(e.doc)
        e.selection = [a, b, c]
        # Box of the movable items: (0, 0) → (40, 30), center (20, 15).
        self.assertTrue(e.move_selection_to("x", 120))
        self.assertFalse(e.move_selection_to("y", 15))    # already there: no step
        self.assertEqual(e.doc.get(a)["center"], (110, 10))
        self.assertEqual(e.doc.get(b)["center"], (140, 30))
        self.assertEqual(e.doc.get(c)["center"], (500, 500))
        e.undo()
        self.assertEqual(e.doc.get(a)["center"], (10, 10))

    def test_copy_code(self):
        e = ed()
        a = e.doc.add({"kind": "circle", "name": "moeda", "center": (1, 2), "radius": 3})
        e.selection = [a]
        self.assertEqual(e.copy_code(), "moeda = Circle(center=(1, 2), radius=3)")


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="test_editor_files_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_save_load_round_trip_backup_and_relative_images(self):
        doc = LevelDoc((500, 300))
        img = os.path.join(self.dir, "arte", "x.png")
        doc.add({"kind": "image", "file": img, "center": (1, 2), "width": 3, "height": 4})
        doc.add({"kind": "rect", "name": "chao", "groups": ["g"], "center": (5, 5),
                 "width": 10, "height": 2})
        path = os.path.join(self.dir, "fase.json")
        doc.save(path)
        self.assertFalse(doc.dirty)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["items"][0]["file"], "arte/x.png")
        parse(data)                                     # a valid level file
        again = LevelDoc.load(path)
        self.assertEqual([{k: v for k, v in i.items() if k != "id"} for i in again.items],
                         [{k: v for k, v in i.items() if k != "id"} for i in doc.items])
        self.assertEqual(again.image_path(again.items[0]), img)
        doc.save(path)
        self.assertTrue(os.path.exists(path + ".bak"))

    def test_save_as_rebases_image_paths(self):
        doc = LevelDoc()
        doc.add({"kind": "image", "file": os.path.join(self.dir, "x.png"),
                 "center": (0, 0), "width": 1, "height": 1})
        doc.save(os.path.join(self.dir, "a.json"))
        sub = os.path.join(self.dir, "sub")
        os.makedirs(sub)
        doc.save(os.path.join(sub, "b.json"))
        with open(os.path.join(sub, "b.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["items"][0]["file"], "../x.png")



class TestPrimaryHeldSelects(unittest.TestCase):
    """Primary (Cmd / Ctrl) held in Pan or a drawing tool: a press is a Select
    press; the tool stays. Decided at the press — a gesture never switches."""

    def setUp(self):
        self.e = ed()
        self.a = self.e.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        self.b = self.e.doc.add({"kind": "rect", "center": (300, 100), "width": 40, "height": 20})
        self.e.history.commit()

    def test_click_selects_and_the_tool_stays(self):
        from scena_editor.tools import SPRING_TOOLS
        for tool in SPRING_TOOLS:
            with self.subTest(tool=tool):
                e = self.e
                e.set_tool(tool)
                e.selection = []
                e.select_held = True
                click(e, (100, 100))
                self.assertEqual(e.selection, [self.a])
                self.assertEqual(e.tool, tool)
                self.assertEqual(len(e.doc.items), 2)          # nothing drawn
                click(e, (300, 100), shift=True)               # Shift still adds
                self.assertEqual(e.selection, [self.a, self.b])
                e.select_held = False

    def test_drag_moves_as_one_step(self):
        e = self.e
        e.set_tool("rect")
        e.select_held = True
        drag(e, (100, 100), (150, 100))
        self.assertEqual(e.doc.get(self.a)["center"], (150, 100))
        self.assertEqual(e.tool, "rect")
        e.undo()
        self.assertEqual(e.doc.get(self.a)["center"], (100, 100))

    def test_releasing_primary_mid_drag_finishes_the_move(self):
        e = self.e
        e.set_tool("ellipse")
        e.select_held = True
        e.pointer_down(100, 100)
        e.select_held = False
        e.pointer_move(130, 100)
        e.pointer_up(130, 100)
        self.assertEqual(e.doc.get(self.a)["center"], (130, 100))
        self.assertEqual(len(e.doc.items), 2)

    def test_pressing_primary_mid_draw_keeps_drawing(self):
        e = self.e
        e.set_tool("rect")
        e.pointer_down(500, 500)
        e.select_held = True
        e.pointer_move(560, 540)
        e.pointer_up(560, 540)
        self.assertEqual(len(e.doc.items), 3)
        self.assertEqual(e.single()["kind"], "rect")

    def test_pan_tool_box_selects(self):
        e = self.e
        e.set_tool("hand")
        e.select_held = True
        drag(e, (50, 50), (350, 150))
        self.assertEqual(sorted(e.selection), sorted([self.a, self.b]))
        self.assertEqual(list(e.viewport.look), [0.0, 0.0])    # no pan

    def test_polygon_keeps_its_points(self):
        e = self.e
        e.set_tool("polygon")
        for p in ((500, 500), (600, 500)):
            click(e, p)
        e.select_held = True
        click(e, (100, 100))
        e.double_click(100, 100)                               # does not close it
        self.assertEqual(e.selection, [self.a])
        self.assertEqual(e.pending, [(500, 500), (600, 500)])
        e.select_held = False
        click(e, (550, 600))
        self.assertTrue(e.key("ENTER"))
        self.assertEqual(len(e.single()["points"]), 3)

    def test_standby_cursor_and_hint(self):
        from scena_editor.i18n import t
        e = self.e
        e.set_tool("rect")
        self.assertEqual(e.cursor(100, 100), "cross")
        e.select_held = True
        self.assertTrue(e.select_standby)
        self.assertEqual(e.cursor(100, 100), "move")           # over a shape, as Select
        self.assertEqual(e.cursor(700, 700), "arrow")
        self.assertEqual(e.hint(), t("hint.select", alt=ALT_LABEL))
        e.set_tool("select")
        self.assertFalse(e.select_standby)                     # Select is not "standby"
        e.set_tool("hand")
        self.assertEqual(e.cursor(700, 700), "arrow")
        e.select_held = False
        self.assertEqual(e.cursor(700, 700), "move")


_point = hst.tuples(hst.integers(0, 900), hst.integers(0, 700))
_action = hst.one_of(
    hst.tuples(hst.just("tool"), hst.sampled_from(["select", "rect", "ellipse", "circle",
                                                   "line", "point"])),
    hst.tuples(hst.just("drag"), _point, _point, hst.booleans()),
    hst.tuples(hst.just("click"), _point, hst.booleans()),
    hst.tuples(hst.just("key"), hst.sampled_from(["DEL", "ESC", "LEFT", "UP", "V", "R", "P", "A"])),
    hst.tuples(hst.just("undo")),
    hst.tuples(hst.just("redo")),
    hst.tuples(hst.just("dup")),
    hst.tuples(hst.just("all")),
    hst.tuples(hst.just("pack"), hst.sampled_from("xy")),
    hst.tuples(hst.just("handle"), hst.integers(0, 9), _point, hst.booleans()),
)


class TestUndoProperty(unittest.TestCase):
    """Any edit sequence: undoing every step returns to the empty level, and
    redoing every step returns to the end — exactly (snapshots)."""

    @settings(deadline=None)
    @given(actions=hst.lists(_action, max_size=25))
    def test_undo_all_then_redo_all(self, actions):
        e = ed()
        start = e.doc.snapshot()
        for a in actions:
            if a[0] == "tool":
                e.set_tool(a[1])
            elif a[0] == "drag":
                drag(e, a[1], a[2], shift=a[3])
            elif a[0] == "click":
                click(e, a[1], shift=a[2])
            elif a[0] == "key":
                e.key(a[1])
            elif a[0] == "undo":
                e.undo()
            elif a[0] == "redo":
                e.redo()
            elif a[0] == "all":
                e.select_all()
            elif a[0] == "pack":
                e.pack(a[1])
            elif a[0] == "handle":
                hs = e.handles()
                if hs:
                    h = hs[a[1] % len(hs)]
                    drag(e, (h.x, h.y), a[2], shift=a[3])
            else:
                e.duplicate()
            parse({"format": "scena-level", "version": 1, "size": list(e.doc.size),
                   "items": e.doc.to_file_dict()["items"]})      # always a valid level
            self.assertTrue(all(e.doc.has(i) for i in e.selection))
        while e.redo():
            pass
        end = e.doc.snapshot()
        while e.undo():
            pass
        self.assertEqual(e.doc.snapshot()[1], start[1])
        while e.redo():
            pass
        self.assertEqual(e.doc.snapshot(), end)


if __name__ == "__main__":
    unittest.main()
