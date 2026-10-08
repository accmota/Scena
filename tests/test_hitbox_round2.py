"""Hitbox parts, round 2: ``px_rect`` / ``px_circle``, ``sprite.showing()``,
and a linked ``active`` (``hb["active"] @= fn``).

Design: design/Sprite Design.md — "Pixel shapes and linked active".

Run headless:

    python -m unittest tests.test_hitbox_round2 -v
"""

import inspect
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import given, strategies as hst  # noqa: E402

import hypothesis_support  # noqa: E402,F401  (loads the SCENA_HYPOTHESIS_PROFILE)

from scena import (  # noqa: E402
    Circle, Sheet, Sprite, Svg, clock, collide, collide_exit,
)
from scena.collision import get_collision_system, reset_collision_system  # noqa: E402
from scena.hitbox import _LINKED_PARTS  # noqa: E402
from scena.shapes import get_xy  # noqa: E402
from scena.state import CallableAssignError, LinkedAttributeError  # noqa: E402

from tests.system_support import SystemTestCase  # noqa: E402
from tests.test_hitbox_parts import PartTestCase, _spec_bounds  # noqa: E402
from tests.test_sprite import (  # noqa: E402
    _write_padded_png,
    _write_rect_png,
)


def _cx_cy(specs):
    x0, y0, x1, y1 = _spec_bounds(specs)
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0, y1 - y0)


class Round2Case(PartTestCase):
    """64×64 art at 1 px = 1 design unit, centre pivot unless a test says so."""

    def still(self, *, name="art.png", size=64, **kw):
        path = self.tmp(name)
        _write_rect_png(path, size, size)
        kw.setdefault("center", self.at(0, 0))
        return self.track(Sprite(path, width=size, height=size, hitbox_shape="rect", **kw))

    def strip(self, *, cols=4, cell=32, fps=60, name="strip.png", **sheet_kw):
        path = self.tmp(name)
        _write_rect_png(path, cell * cols, cell)
        return Sheet(path, cols=cols, fps=fps, **sheet_kw)

    def fighter_atlas(self, *, trimmed=False):
        """Two 32×16 cells; "punch" carries an authored box (20, 2, 12, 12)."""
        png = self.tmp("fighter.png")
        _write_rect_png(png, 64, 16)
        atlas = self.tmp("fighter.json")
        punch = {"filename": "punch", "frame": {"x": 32, "y": 0, "w": 32, "h": 16},
                 "hitboxes": [{"x": 20, "y": 2, "w": 12, "h": 12}]}
        if trimmed:
            # Packed 26×12 of a 32×16 source, trimmed 4 px left / 2 px top.
            punch = {"filename": "punch", "frame": {"x": 32, "y": 0, "w": 26, "h": 12},
                     "trimmed": True,
                     "spriteSourceSize": {"x": 4, "y": 2, "w": 26, "h": 12},
                     "sourceSize": {"w": 32, "h": 16},
                     "hitboxes": [{"x": 20, "y": 2, "w": 12, "h": 12}]}
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({"frames": [
                {"filename": "idle", "frame": {"x": 0, "y": 0, "w": 32, "h": 16}},
                punch,
            ]}, f)
        return Sheet(png, atlas=atlas)


# --------------------------------------------------------------------------
# A. px_rect / px_circle
# --------------------------------------------------------------------------

class TestPxShapeApi(Round2Case):

    def test_signature_shows_readable_defaults(self):
        sig = inspect.signature(Sprite.add_hitbox)
        self.assertEqual(sig.parameters["source"].default, "each")
        self.assertIsNone(sig.parameters["px_rect"].default)
        self.assertIsNone(sig.parameters["px_circle"].default)

    def test_px_rect_parse_errors(self):
        s = self.still()
        for bad in ((1, 2, 3), (1, 2, 3, 4, 5), "1,2,3,4", 5, None.__class__):
            with self.assertRaises(TypeError, msg=repr(bad)):
                s.add_hitbox(px_rect=bad)
        with self.assertRaises(TypeError):
            s.add_hitbox(px_rect=(1, 2, True, 4))
        with self.assertRaises(TypeError):
            s.add_hitbox(px_rect=(1, "2", 3, 4))
        for bad in ((math.nan, 0, 1, 1), (0, math.inf, 1, 1), (0, 0, -1, 1), (0, 0, 1, -2)):
            with self.assertRaises(ValueError, msg=repr(bad)):
                s.add_hitbox(px_rect=bad)
        self.assertEqual(s.add_hitbox(px_rect=[0, 0, 0, 0]).px_rect, (0.0, 0.0, 0.0, 0.0))

    def test_px_circle_parse_errors(self):
        s = self.still()
        with self.assertRaises(TypeError):
            s.add_hitbox(px_circle=(1, 2))
        with self.assertRaises(ValueError):
            s.add_hitbox(px_circle=(1, 2, -3))
        with self.assertRaises(ValueError):
            s.add_hitbox(px_circle=(math.nan, 2, 3))
        self.assertEqual(s.add_hitbox(px_circle=(1, 2, 0)).px_circle, (1.0, 2.0, 0.0))

    def test_one_px_shape_per_part(self):
        s = self.still()
        with self.assertRaises(TypeError):
            s.add_hitbox(px_rect=(0, 0, 4, 4), px_circle=(0, 0, 4))

    def test_px_shape_refuses_every_explicit_art_knob(self):
        # Even the default value, written out, is refused (sentinel, not ==).
        s = self.still()
        for knob, value in (("shape", "auto"), ("source", "each"),
                            ("anchor", "center"), ("scale", 1.0)):
            with self.assertRaises(TypeError, msg=knob) as cm:
                s.add_hitbox(px_rect=(0, 0, 4, 4), **{knob: value})
            self.assertIn(knob, str(cm.exception))
        # Without a px shape the art knobs work as in round 1.
        self.assertEqual(s.add_hitbox(source="each").source, "each")

    def test_active_takes_a_flag_not_a_function(self):
        s = self.still()
        with self.assertRaises(TypeError) as cm:
            s.add_hitbox(active=lambda: True)
        self.assertIn('["active"] @=', str(cm.exception))

    def test_svg_host_refuses_px(self):
        svg = self.track(Svg(
            '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
            '<rect x="8" y="8" width="16" height="16" fill="red"/></svg>',
            center=self.at(0, 0), size=32,
        ))
        with self.assertRaises(TypeError):
            svg.add_hitbox(px_rect=(0, 0, 4, 4))
        hb = svg.add_hitbox()
        with self.assertRaises(TypeError):
            hb.px_circle = (1, 1, 1)

    def test_live_writes(self):
        s = self.still()
        hb = s.add_hitbox(group="a", px_rect=(0, 0, 8, 8))
        self.assertIsNone(hb.px_circle)
        hb.px_circle = (32, 32, 5)
        self.assertIsNone(hb.px_rect)
        self.assertEqual(hb.px_circle, (32.0, 32.0, 5.0))
        _cx, _cy, w, h = _cx_cy(hb._collision_specs())
        self.assertAlmostEqual(w, 10.0, places=3)
        for knob, value in (("shape", "rect"), ("source", "all"),
                            ("anchor", "bottom"), ("scale", 2)):
            with self.assertRaises(TypeError, msg=knob):
                setattr(hb, knob, value)
        hb.px_rect = None           # not the one in use: no-op
        self.assertEqual(hb.px_circle, (32.0, 32.0, 5.0))
        hb.px_circle = None         # back to the art
        self.assertIsNone(hb.px_circle)
        self.assertEqual((hb.shape, hb.source), ("auto", "each"))
        _cx, _cy, w, h = _cx_cy(hb._collision_specs())
        self.assertAlmostEqual(w, 64.0, places=3)   # the whole opaque cell
        hb.scale = 0.5                       # art knobs work again
        self.assertEqual(hb.scale, (0.5, 0.5))

    def test_repr_names_the_px_shape(self):
        hb = self.still().add_hitbox(group="a", px_circle=(1, 2, 3))
        self.assertIn("px_circle=(1.0, 2.0, 3.0)", repr(hb))


class TestPxShapePlacement(Round2Case):

    def test_px_circle_centre_and_radius(self):
        # Centre pivot at pixel (32, 32); pixel (40, 16) is +8 right, +16 up.
        s = self.still()
        hb = s.add_hitbox(group="a", px_circle=(40, 16, 6))
        cx, cy, w, h = _cx_cy(hb._collision_specs())
        ox, oy = self.at(0, 0)
        self.assertAlmostEqual(cx, ox + 8.0, places=3)
        self.assertAlmostEqual(cy, oy + 16.0, places=3)
        self.assertAlmostEqual(w, 12.0, places=3)
        self.assertAlmostEqual(h, 12.0, places=3)

    def test_px_rect_is_top_left_corner_y_down(self):
        s = self.still()
        hb = s.add_hitbox(group="a", px_rect=(0, 0, 10, 4))   # top-left corner of the PNG
        x0, y0, x1, y1 = _spec_bounds(hb._collision_specs())
        ox, oy = self.at(0, 0)
        self.assertAlmostEqual(x0, ox - 32.0, places=3)
        self.assertAlmostEqual(x1, ox - 22.0, places=3)
        self.assertAlmostEqual(y1, oy + 32.0, places=3)
        self.assertAlmostEqual(y0, oy + 28.0, places=3)

    def test_px_rect_equals_the_same_atlas_box(self):
        # The oracle: an authored atlas box with the same numbers.
        sheet = self.fighter_atlas()
        s = self.track(Sprite(sheet, frame="punch", center=self.at(0, 0),
                              width=32, height=16, hitbox_shape="rect"))
        atlas_part = s.add_hitbox(group="a")                   # auto: reads the box
        px_part = s.add_hitbox(group="b", px_rect=(20, 2, 12, 12))
        for pose in ({}, {"flip_x": True}, {"angle": 30}, {"tilt": 20},
                     {"offset": (5, -3)}):
            for k, v in pose.items():
                setattr(s, k, v)
            a = _spec_bounds(atlas_part._collision_specs())
            b = _spec_bounds(px_part._collision_specs())
            for u, v in zip(a, b):
                self.assertAlmostEqual(u, v, places=6, msg=repr(pose))

    def test_trimmed_atlas_frame_uses_source_coordinates(self):
        sheet = self.fighter_atlas(trimmed=True)
        s = self.track(Sprite(sheet, frame="punch", center=self.at(0, 0),
                              width=32, height=16, hitbox_shape="rect"))
        atlas_part = s.add_hitbox(group="a")
        px_part = s.add_hitbox(group="b", px_rect=(20, 2, 12, 12))
        a = _spec_bounds(atlas_part._collision_specs())
        b = _spec_bounds(px_part._collision_specs())
        for u, v in zip(a, b):
            self.assertAlmostEqual(u, v, places=6)
        # Untrimmed source 32×16, centre pivot (16, 8): the box centre (26, 8)
        # is +10 right, 0 up — not measured in the 26×12 packed rect.
        cx, cy, _w, _h = _cx_cy(px_part._collision_specs())
        ox, oy = self.at(0, 0)
        self.assertAlmostEqual(cx - ox, 10.0, places=3)
        self.assertAlmostEqual(cy - oy, 0.0, places=3)

    def test_sheet_anchor_bottom_measures_from_the_feet(self):
        path = self.tmp("tall.png")
        _write_rect_png(path, 64, 64)
        sheet = Sheet(path, anchor="bottom")
        s = self.track(Sprite(sheet, width=64, height=64, center=self.at(0, 0), hitbox_shape="rect"))
        hb = s.add_hitbox(group="a", px_rect=(28, 0, 8, 8))   # top of the art
        x0, y0, x1, y1 = _spec_bounds(hb._collision_specs())
        ox, oy = self.at(0, 0)
        self.assertAlmostEqual(y1, oy + 64.0, places=3)        # centre = the feet
        self.assertAlmostEqual(y0, oy + 56.0, places=3)
        self.assertAlmostEqual((x0 + x1) / 2, ox, places=3)

    def test_clip_offset_moves_the_box_with_the_art(self):
        sheet = self.strip(cols=2, cell=32)
        sheet.clip("moved", [1], offset=(10, 0))
        sheet.clip("plain", [0])
        s = self.track(Sprite(sheet, width=32, height=32, center=self.at(0, 0), hitbox_shape="rect"))
        hb = s.add_hitbox(group="a", px_rect=(12, 12, 8, 8))   # the cell's centre
        s.play("plain")
        cx0, _cy, _w, _h = _cx_cy(hb._collision_specs())
        s.play("moved")
        cx1, _cy, _w, _h = _cx_cy(hb._collision_specs())
        self.assertAlmostEqual(cx1 - cx0, 10.0, places=3)

    def test_sprite_offset_and_flip_follow_the_paint(self):
        s = self.still()
        hb = s.add_hitbox(group="a", px_circle=(48, 32, 4))      # 16 px right of centre
        ox, oy = self.at(0, 0)
        self.assertAlmostEqual(_cx_cy(hb._collision_specs())[0], ox + 16.0, places=3)
        s.flip_x = True
        self.assertAlmostEqual(_cx_cy(hb._collision_specs())[0], ox - 16.0, places=3)
        s.flip_x = False
        s.offset = (5, 7)
        cx, cy, _w, _h = _cx_cy(hb._collision_specs())
        self.assertAlmostEqual(cx, ox + 21.0, places=3)
        self.assertAlmostEqual(cy, oy + 7.0, places=3)

    def test_rotation_and_tilt_turn_the_box(self):
        s = self.still()
        hb = s.add_hitbox(group="a", px_circle=(48, 32, 2))
        ox, oy = self.at(0, 0)
        s.angle = 90
        cx, cy, _w, _h = _cx_cy(hb._collision_specs())
        self.assertAlmostEqual(cx, ox, places=3)
        self.assertAlmostEqual(cy, oy + 16.0, places=3)
        s.angle = 0
        s.tilt = 90
        cx, cy, _w, _h = _cx_cy(hb._collision_specs())
        self.assertAlmostEqual(cx, ox, places=3)
        self.assertAlmostEqual(cy, oy + 16.0, places=3)

    def test_stretched_circle_is_an_ellipse(self):
        path = self.tmp("sq.png")
        _write_rect_png(path, 64, 64)
        s = self.track(Sprite(path, width=64, height=32, center=self.at(0, 0), hitbox_shape="rect"))
        hb = s.add_hitbox(group="a", px_circle=(32, 32, 10))
        (spec,) = hb._collision_specs()
        self.assertEqual(spec[0], "ellipse")
        self.assertAlmostEqual(spec[3], 10.0, places=3)   # rx
        self.assertAlmostEqual(spec[4], 5.0, places=3)    # ry: half the height

    def test_grid_sheet_numbers_are_cell_local(self):
        sheet = self.strip(cols=2, cell=32)
        s = self.track(Sprite(sheet, frame=0, width=32, height=32,
                              center=self.at(0, 0), hitbox_shape="rect"))
        hb = s.add_hitbox(group="a", px_rect=(0, 0, 4, 4))
        first = _spec_bounds(hb._collision_specs())
        s.frame = 1
        second = _spec_bounds(hb._collision_specs())
        for u, v in zip(first, second):
            self.assertAlmostEqual(u, v, places=6)

    def test_box_past_the_cell_is_not_clamped(self):
        s = self.still(size=100)
        hb = s.add_hitbox(group="a", px_rect=(80, 80, 40, 40))
        x0, y0, x1, y1 = _spec_bounds(hb._collision_specs())
        ox, oy = self.at(0, 0)
        self.assertAlmostEqual(x1, ox + 70.0, places=3)        # 120 − 50: past the art
        self.assertAlmostEqual(y0, oy - 70.0, places=3)

    def test_same_numbers_in_a_cell_of_another_size_move(self):
        # Documented: numbers are the cell on screen's pixels.
        small = self.tmp("small.png")
        big = self.tmp("big.png")
        _write_rect_png(small, 32, 32)
        _write_rect_png(big, 64, 32)
        sheet = Sheet([small, big])
        s = self.track(Sprite(sheet, frame=0, center=self.at(0, 0), hitbox_shape="rect"))
        hb = s.add_hitbox(group="a", px_circle=(16, 16, 2))
        cx0 = _cx_cy(hb._collision_specs())[0]
        s.frame = 1
        cx1 = _cx_cy(hb._collision_specs())[0]
        self.assertNotAlmostEqual(cx0, cx1, places=3)


class TestPxShapeCache(Round2Case):

    def test_same_geometry_cells_keep_the_epoch(self):
        sheet = self.strip(cols=4, cell=32)
        sheet.clip("run", [0, 1, 2, 3], fps=60)
        s = self.track(Sprite(sheet, width=32, height=32, center=self.at(0, 0),
                              hitbox_shape="rect", group="hero"))
        hb = s.add_hitbox(group="hurt", px_rect=(4, 4, 8, 8))
        self.dot(0, 0)

        @collide("bullet", "hurt")
        def _h(a, b, info):
            pass

        s.play("run")
        self.step()
        epoch0 = hb._collision_epoch
        key0 = hb._hitbox_baked_key
        seen = set()
        for _ in range(8):
            clock.advance(1.0 / 60.0)
            self.step()
            seen.add(s.frame)
            self.assertEqual(hb._collision_epoch, epoch0)
            self.assertEqual(hb._hitbox_baked_key, key0)
        self.assertGreater(len(seen), 2)

    def test_geometry_change_rebakes(self):
        small = self.tmp("s.png")
        big = self.tmp("b.png")
        _write_rect_png(small, 32, 32)
        _write_rect_png(big, 64, 32)
        sheet = Sheet([small, big])
        s = self.track(Sprite(sheet, frame=0, center=self.at(0, 0), hitbox_shape="rect"))
        hb = s.add_hitbox(group="a", px_rect=(0, 0, 4, 4))
        hb._collision_specs()
        key0 = hb._hitbox_baked_key
        s.frame = 1
        hb._collision_specs()
        self.assertNotEqual(hb._hitbox_baked_key, key0)
        self.assertEqual(hb._hitbox_baked_key[:2], (64.0, 32.0))


class TestPxShapeProperty(Round2Case):
    _n = 0

    @given(
        # Atlas boxes are whole pixels, and a zero-size one is dropped.
        rect=hst.tuples(
            hst.integers(-40, 60), hst.integers(-40, 40),
            hst.integers(1, 40), hst.integers(1, 40),
        ),
        angle=hst.floats(-360, 360),
        tilt=hst.floats(-80, 80),
        flip_x=hst.booleans(),
        flip_y=hst.booleans(),
        offset=hst.tuples(hst.floats(-20, 20), hst.floats(-20, 20)),
        scale=hst.floats(0.25, 3.0),
    )
    def test_px_rect_matches_an_atlas_box_in_any_pose(
        self, rect, angle, tilt, flip_x, flip_y, offset, scale,
    ):
        # Atlases are cached by path: a fresh name per example.
        TestPxShapeProperty._n += 1
        png = self.tmp(f"prop{self._n}.png")
        _write_rect_png(png, 64, 16)
        atlas = self.tmp(f"prop{self._n}.json")
        x, y, w, h = rect
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({"frames": [
                {"filename": "a", "frame": {"x": 0, "y": 0, "w": 32, "h": 16},
                 "hitboxes": [{"x": x, "y": y, "w": w, "h": h}]},
            ]}, f)
        sheet = Sheet(png, atlas=atlas)
        s = Sprite(sheet, width=32, height=16, center=self.at(0, 0), hitbox_shape="rect",
                   flip_x=flip_x, flip_y=flip_y)
        try:
            s.angle = angle
            s.tilt = tilt
            s.offset = offset
            s.scale = scale
            atlas_part = s.add_hitbox(group="a")
            px_part = s.add_hitbox(group="b", px_rect=rect)
            want = _spec_bounds(atlas_part._collision_specs())
            got_specs = px_part._collision_specs()
            got = _spec_bounds(got_specs)
            for u, v in zip(want, got):
                self.assertAlmostEqual(u, v, places=5)
            # The cheap proxy holds every prim (broad phase must not drop it).
            px0, py0, px1, py1 = px_part._proxy_aabb()
            self.assertLessEqual(px0, got[0] + 1e-6)
            self.assertLessEqual(py0, got[1] + 1e-6)
            self.assertGreaterEqual(px1, got[2] - 1e-6)
            self.assertGreaterEqual(py1, got[3] - 1e-6)
        finally:
            s.destroy()


# --------------------------------------------------------------------------
# B. sprite.showing(...)
# --------------------------------------------------------------------------

class TestShowing(Round2Case):

    def named_sheet(self):
        names = []
        for i, wh in enumerate(((32, 32), (32, 32), (32, 32), (32, 32))):
            p = self.tmp(f"hero_{i}.png")
            _write_rect_png(p, *wh)
            names.append(p)
        sheet = Sheet(names, fps=60)
        sheet.clip("idle", [0, 1], fps=60)
        sheet.clip("punch", [2, 3], fps=60)
        return sheet, names

    def test_selectors(self):
        sheet, names = self.named_sheet()
        s = self.track(Sprite(sheet, frame=2, center=self.at(0, 0)))
        self.assertTrue(s.showing("punch"))
        self.assertFalse(s.showing("idle"))
        self.assertTrue(s.showing(2))
        self.assertFalse(s.showing(3))
        self.assertTrue(s.showing(names[2]))
        self.assertTrue(s.showing((0, names[2])))
        self.assertTrue(s.showing([names[3], "punch"]))
        self.assertFalse(s.showing(["idle", 3]))

    def test_follows_the_playhead(self):
        sheet, _names = self.named_sheet()
        s = self.track(Sprite(sheet, center=self.at(0, 0)))
        s.play("punch")
        self.assertTrue(s.showing(2))
        clock.advance(1.0 / 60.0)
        self.assertTrue(s.showing(3))
        self.assertFalse(s.showing(2))

    def test_yoyo_and_next(self):
        path = self.tmp("yo.png")
        _write_rect_png(path, 96, 32)
        sheet = Sheet(path, cols=3, fps=60)
        sheet.clip("yo", [0, 1, 2], fps=60, yoyo=True)
        sheet.clip("rest", [0], fps=60)
        s = self.track(Sprite(sheet, center=self.at(0, 0)))
        s.play("yo")
        seen = []
        for _ in range(5):
            seen.append(s.showing(2))
            clock.advance(1.0 / 60.0)
        self.assertEqual(seen, [False, False, True, False, False])
        s.play("yo", loops=1, next="rest")
        for _ in range(6):
            clock.advance(1.0 / 60.0)
        self.assertTrue(s.showing("rest"))

    def test_shared_cell_counts_in_both_clips(self):
        sheet, _names = self.named_sheet()
        sheet.clip("wave", [1, 2], fps=60)
        s = self.track(Sprite(sheet, frame=2, center=self.at(0, 0)))
        self.assertTrue(s.showing("wave"))
        self.assertTrue(s.showing("punch"))

    def test_errors(self):
        sheet, _names = self.named_sheet()
        s = self.track(Sprite(sheet, frame=0, center=self.at(0, 0)))
        for bad in ("each", "clip", "all"):
            with self.assertRaises(ValueError, msg=bad):
                s.showing(bad)
        for bad in ((), [], "nope", 99, -1, ""):
            with self.assertRaises(ValueError, msg=repr(bad)):
                s.showing(bad)
        for bad in (True, 1.5, None, {"punch"}):
            with self.assertRaises(TypeError, msg=repr(bad)):
                s.showing(bad)

    def test_cache_is_hit_and_cleared_by_clip(self):
        sheet, _names = self.named_sheet()
        s = self.track(Sprite(sheet, frame=0, center=self.at(0, 0)))
        s.showing("punch")
        cached = sheet._selector_cache[("punch")]
        s.showing("punch")
        self.assertIs(sheet._selector_cache["punch"], cached)
        sheet.clip("punch", [0], fps=60)            # replaced (warns)
        self.assertIsNone(sheet._selector_cache)
        self.assertTrue(s.showing("punch"))


# --------------------------------------------------------------------------
# C. linked active
# --------------------------------------------------------------------------

class TestLinkedActive(Round2Case):

    def setUp(self):
        super().setUp()
        self.addCleanup(_LINKED_PARTS.clear)

    def part(self, **kw):
        s = self.still(group="hero")
        return s, s.add_hitbox(group="hurt", px_rect=(0, 0, 64, 64), **kw)

    def test_link_evaluates_once_and_unlink_keeps_the_value(self):
        s, hb = self.part()
        calls = []

        def gate():
            calls.append(1)
            return False

        hb["active"] @= gate
        self.assertEqual(len(calls), 1)            # evaluated on the @= line
        self.assertFalse(hb._active)
        self.assertIn(hb, _LINKED_PARTS)
        self.assertTrue(hb["active"].linked)
        hb["active"].unlink()
        self.assertNotIn(hb, _LINKED_PARTS)
        self.assertFalse(hb.active)                 # last value kept
        hb.active = True                            # plain writes work again
        self.assertTrue(hb.active)

    def test_read_calls_the_function(self):
        s, hb = self.part()
        box = {"on": True}
        hb["active"] @= lambda: box["on"]
        box["on"] = False
        self.assertFalse(hb.active)
        box["on"] = True
        self.assertTrue(hb.active)

    def test_write_while_linked_and_callable_assign(self):
        s, hb = self.part()
        hb["active"] @= lambda: True
        with self.assertRaises(LinkedAttributeError) as cm:
            hb.active = False
        self.assertIn("unlink()", str(cm.exception))
        with self.assertRaises(CallableAssignError) as cm:
            hb.active = lambda: False
        self.assertIn("['active'] @=", str(cm.exception))

    def test_only_active_links(self):
        s, hb = self.part()
        with self.assertRaises(TypeError):
            hb["scale"] @= lambda: 2
        with self.assertRaises(TypeError):
            hb["px_rect"]
        with self.assertRaises(TypeError):
            hb["active"] = True
        with self.assertRaises(TypeError):
            hb["active"] @= True
        self.assertNotIn(hb, _LINKED_PARTS)

    def test_bad_results_and_exceptions_carry_both_sites(self):
        s, hb = self.part()
        with self.assertRaises(TypeError) as cm:
            hb["active"] @= lambda: "yes"
        notes = " ".join(getattr(cm.exception, "__notes__", []))
        self.assertIn("test_hitbox_round2.py", notes)
        self.assertIn("hitbox made at", notes)
        self.assertNotIn(hb, _LINKED_PARTS)         # a failed @= does not link

        box = {"boom": False}

        def gate():
            if box["boom"]:
                raise KeyError("frame table")
            return True

        hb["active"] @= gate
        box["boom"] = True
        with self.assertRaises(KeyError) as cm:
            get_collision_system().step()
        notes = " ".join(getattr(cm.exception, "__notes__", []))
        self.assertIn("formula linked to hitbox.active", notes)

    def test_zero_and_one_are_flags(self):
        s, hb = self.part()
        hb["active"] @= lambda: 0
        self.assertFalse(hb.active)

    def test_self_read_raises(self):
        s, hb = self.part()
        with self.assertRaises(ValueError) as cm:
            hb["active"] @= lambda: not hb.active
        self.assertIn("reads itself", str(cm.exception))

    def test_skipped_while_out_of_play(self):
        s, hb = self.part()
        calls = []

        def gate():
            calls.append(1)
            return True

        hb["active"] @= gate
        n = len(calls)
        s.active = False                            # parked
        get_collision_system().step()
        self.assertEqual(len(calls), n)
        s.active = True
        get_collision_system().step()
        self.assertEqual(len(calls), n + 1)
        s.collidable = True
        s.collidable = False                        # opt out: parts leave too
        get_collision_system().step()
        self.assertEqual(len(calls), n + 1)

    def test_link_runs_once_per_step_not_per_contact(self):
        """HP5 (graphics review): the engine read the public ``active`` for a
        part in play, so a linked flag ran its function once per contact, and
        a handler that changed the input retired the part mid-dispatch
        (``@collide_exit`` with no enter). One evaluation per step, at its
        start (``_refresh_linked_parts``); the dispatch reads that value."""
        s, hb = self.part()
        box = {"on": True}
        calls, hits, exits = [], [], []

        def gate():
            calls.append(1)
            return box["on"]

        hb["active"] @= gate
        bullets = [self.dot(x, 0) for x in (-10, 0, 10)]

        @collide("bullet", "hurt")
        def hit(b, part, info=None):
            hits.append(b)
            box["on"] = False                      # the handler changes the input

        @collide_exit("bullet", "hurt")
        def gone(b, part, info=None):
            exits.append(b)

        n = len(calls)
        get_collision_system().step()
        self.assertEqual(len(calls) - n, 1, "one evaluation per step")
        self.assertEqual(len(hits), len(bullets), "every contact of the step dispatched")
        self.assertEqual(exits, [], "no exit inside the step that entered")
        get_collision_system().step()               # the new value applies next step
        self.assertEqual(sorted(map(id, exits)), sorted(map(id, bullets)))

    def test_removed_and_destroyed_parts_leave_the_index(self):
        s, hb = self.part()
        hb["active"] @= lambda: True
        s.remove_hitbox(hb)
        self.assertNotIn(hb, _LINKED_PARTS)
        s2, hb2 = self.part()
        hb2["active"] @= lambda: True
        s2.destroy()
        self.assertNotIn(hb2, _LINKED_PARTS)

    def test_named_query_refreshes_the_link(self):
        s, hb = self.part()
        box = {"on": False}
        hb["active"] @= lambda: box["on"]
        probe = self.dot(0, 0, group="probe")
        self.assertEqual(probe.collides_with("hurt"), [])
        box["on"] = True                            # no step in between
        self.assertEqual(probe.collides_with("hurt"), [s])

    def test_step_turns_it_on_and_off_with_enter_and_exit(self):
        s, hb = self.part()
        self.dot(0, 0)
        log = []

        @collide("bullet", "hurt")
        def _in(a, b, info):
            log.append(("enter", info.b_hitbox is hb))

        @collide_exit("bullet", "hurt")
        def _out(a, b, info):
            log.append("exit")

        box = {"on": False}
        hb["active"] @= lambda: box["on"]
        self.step()
        self.assertEqual(log, [])
        box["on"] = True
        self.step()
        self.assertEqual(log, [("enter", True)])
        box["on"] = False
        self.step()
        self.assertEqual(log, [("enter", True), "exit"])

    def test_links_survive_a_collision_system_reset(self):
        s, hb = self.part()
        calls = []
        hb["active"] @= lambda: calls.append(1) or True
        n = len(calls)
        reset_collision_system()
        get_collision_system().step()
        self.assertEqual(len(calls), n + 1)


class TestLinkedActiveFrames(SystemTestCase, unittest.TestCase):
    """Real frames (``_simulate_frame``): update → processes → collision."""

    def setUp(self):
        super().setUp()
        self.addCleanup(_LINKED_PARTS.clear)
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        path = os.path.join(self._dir.name, "fighter.png")
        _write_rect_png(path, 32 * 6, 32)
        self.sheet = Sheet(path, cols=6, fps=60)
        self.sheet.clip("idle", [0], fps=60)
        self.sheet.clip("punch", [1, 2, 3, 4], fps=60)   # strike on cells 2–3
        self.sheet.clip("hurt", [5], fps=60)
        self.hero = self.track(Sprite(self.sheet, frame=0, width=32, height=32,
                                      center=(0, 0), group="hero", hitbox_shape="rect"))
        self.fist = self.hero.add_hitbox(group="attack", px_rect=(0, 0, 32, 32))
        self.fist["active"] @= lambda: self.hero.showing((2, 3))
        self.dummy = self.track(Circle(center=(0, 0), radius=3, group="dummy"))
        self.log = []

        @collide("attack", "dummy")
        def _hit(a, b, info):
            self.log.append(("enter", self.hero.frame))

        @collide_exit("attack", "dummy")
        def _gone(a, b, info):
            self.log.append(("exit", self.hero.frame))

    def test_enter_on_first_strike_cell_exit_after_last(self):
        self.w.step(2)
        self.hero.play("punch", loops=1, next="idle")
        self.w.step(8)
        self.assertEqual(self.log, [("enter", 2), ("exit", 4)])

    def test_play_in_on_update_has_no_lag(self):
        # The strike cell is the punch's first cell here: play() at step 3
        # (on_update) must be seen by collision (step 4) in the same frame.
        self.fist["active"].unlink()
        self.fist["active"] @= lambda: self.hero.showing((1,))
        started = {}

        def hook(entity, dt):
            if clock.frame == 5 and not started:
                entity.play("punch", loops=1, next="idle")
                started["frame"] = clock.frame

        self.hero.on_update = hook
        entered = {}

        @collide("attack", "dummy")
        def _hit2(a, b, info):
            entered.setdefault("frame", clock.frame)

        self.w.step(8)
        self.assertEqual(entered.get("frame"), started.get("frame"))

    def test_switching_away_mid_strike_turns_the_box_off(self):
        self.hero.play("punch", loops=1, next="idle")
        self.w.step_until(lambda: self.hero.frame == 2, max_frames=10)
        self.w.step(1)
        self.assertEqual(self.log[0][0], "enter")
        self.hero.play("hurt")                      # hit mid-swing: other clip
        self.w.step(1)
        self.assertEqual(self.log[-1], ("exit", 5))
        self.assertFalse(self.fist.active)


if __name__ == "__main__":
    unittest.main()
