"""The cached cull box equals the computed one.

Rule under test (Canvas Design.md, "Offscreen culling", the cache): a body
whose pose revision is trusted keeps its padded cull box until its pose
revision, its look revision (every paint write) or, for a Sprite, its sheet
layout moves. A transient, a custom cull pad or a playing clip skip the cache.
``canvas._CULL_CACHE = False`` computes every box (the oracle).

Random bodies go through random pose and paint operations; after each, the
box the cull uses holds ``_cull_box_full`` and is within a few ``_CULL_SHIFT_EPS``
of it (equal unless a move shifted it).

A body whose pose changed only by moves of its center (Sprite, and the center
models of Circle, Rect, Ellipse) keeps its cached box shifted by the move
(``_CULL_SHIFT``); any other write, a model that is not a center model, or a
Circle by center and perimeter point recomputes.

Bug class guarded: a cull box that outlives what it was built from (a body
that moved or grew a glow is skipped while on screen).
"""
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena import Glow, Neon, st
from scena.shapes import Circle, Ellipse, Polygon, Rect
from scena.sprite import Sheet, Sprite

CV = sys.modules["scena.canvas"]
MEDIA = os.path.join(ROOT, "examples", "media")
TILE = os.path.join(MEDIA, "tilesets", "Tiles", "2.png")
NINJA = os.path.join(MEDIA, "ninja")


def make(r):
    k = r.choice(("rect", "circle", "ellipse", "tile", "sheet", "poly"))
    x, y = r.uniform(-500, 500), r.uniform(-500, 500)
    if k == "rect":
        return k, Rect(center=(x, y), width=r.uniform(5, 80), height=r.uniform(5, 80))
    if k == "circle":
        return k, Circle(center=(x, y), radius=r.uniform(3, 40))
    if k == "ellipse":
        return k, Ellipse(center=(x, y), width=r.uniform(10, 80), height=r.uniform(5, 40))
    if k == "tile":
        return k, Sprite(TILE, size=r.choice((32.0, 64.0)), center=(x, y))
    if k == "sheet":
        sheet = Sheet(anchor="bottom", pixel_size=0.2)
        sheet.strip("run", os.path.join(NINJA, "Run__*.png"), fps=12)
        sheet.strip("idle", os.path.join(NINJA, "Idle__*.png"), fps=8)
        return k, Sprite(sheet, center=(x, y))
    return k, Polygon(points=[(x, y), (x + 30, y), (x + 10, y + 25)])


def operate(r, o, kind):
    op = r.choice(("move", "angle", "scale", "flip", "line_width", "glow", "neon", "unlook",
                   "size", "flash", "play", "stop", "frame", "link"))
    try:
        if op == "move":
            o.move_by(r.uniform(-30, 30), r.uniform(-30, 30), force=True)
        elif op == "angle":
            o.rotate_by(r.uniform(-60, 60), force=True)
        elif op == "scale":
            o.scale = r.choice((0.5, 1.0, 1.8))
        elif op == "flip":
            o.flip_x = not o.flip_x
        elif op == "line_width":
            o.line_width = r.choice((0.0, 2.0, 9.0))
        elif op == "glow":
            o.glow = r.choice(("cyan", Glow("gold", radius=20)))
        elif op == "neon":
            o.visual = Neon("cyan")
        elif op == "unlook":
            o.glow = None
            o.visual = None
        elif op == "size" and kind in ("rect", "ellipse", "tile", "sheet"):
            o.width = r.uniform(10, 120)
        elif op == "flash":
            o.flash()
        elif op == "play" and kind == "sheet":
            o.play(r.choice(("run", "idle")))
        elif op == "stop" and kind == "sheet":
            o.stop()
        elif op == "frame" and kind == "sheet":
            o.stop()
            o.frame = r.randint(0, 3)
        elif op == "link" and kind == "rect":
            st.cx = r.uniform(-200, 200)
            o.center["x"] @= lambda: st.cx
    except (TypeError, ValueError, AttributeError):
        pass                          # a refusal is fine: the box must still agree
    return op


def assert_hugs(tc, got, full, ctx):
    """``got`` holds ``full`` and is within 4 shift pads of it."""
    if full is None or got is None:
        tc.assertEqual(got, full, ctx)
        return
    e = 4 * CV._CULL_SHIFT_EPS
    tc.assertTrue(got[0] <= full[0] and got[1] <= full[1] and got[2] >= full[2] and got[3] >= full[3],
                  f"{ctx}: {got} does not hold {full}")
    tc.assertTrue(full[0] - got[0] <= e and full[1] - got[1] <= e and got[2] - full[2] <= e
                  and got[3] - full[3] <= e, f"{ctx}: {got} is looser than {full}")


class TestCachedEqualsComputed(unittest.TestCase):
    def test_random_bodies_and_operations(self):
        r = random.Random(5)
        cached = checked = 0
        owned = []
        try:
            for i in range(80):
                kind, o = make(r)
                owned.append(o)
                for k in range(10):
                    op = operate(r, o, kind)
                    if r.random() < 0.3:
                        st.cx = r.uniform(-200, 200)      # moves linked bodies, no write
                    key = CV._cull_cache_key(o)
                    got = CV._cull_box(o)
                    assert_hugs(self, got, CV._cull_box_full(o), f"body {i} {kind} op {k} {op}")
                    checked += 1
                    cached += key is not None
        finally:
            for o in owned:
                o.destroy()
        self.assertGreater(cached, checked // 3, "the cache must be used")

    def test_a_still_body_reads_the_cache(self):
        o = Rect(center=(0, 0), width=10, height=10)
        try:
            CV._cull_box(o)
            with mock.patch.object(CV, "_cull_box_full", side_effect=AssertionError("computed")), \
                    mock.patch.object(CV, "_cull_verify", lambda: False):
                self.assertIsNotNone(CV._cull_box(o))
        finally:
            o.destroy()


class TestShiftedBox(unittest.TestCase):
    def test_a_mover_is_shifted_not_recomputed(self):
        for make in (lambda: Rect(center=(0, 0), width=30, height=10, angle=30),
                     lambda: Circle(center=(0, 0), radius=9),
                     lambda: Ellipse(center=(0, 0), width=20, height=8),
                     lambda: Sprite(TILE, size=32.0, center=(0, 0))):
            o = make()
            try:
                o.glow = "cyan"
                CV._cull_box(o)
                calls = []
                real = CV._cull_box_full
                with mock.patch.object(CV, "_cull_box_full", lambda x: calls.append(1) or real(x)), \
                        mock.patch.object(CV, "_cull_verify", lambda: False):
                    for step in range(20):
                        o.move_by(7.5, -3.25)
                        got = CV._cull_box(o)
                        assert_hugs(self, got, real(o), f"{type(o).__name__} step {step}")
                        o.center = (float(o.center.x) + 1e5, float(o.center.y))   # far moves too
                        assert_hugs(self, CV._cull_box(o), real(o), f"{type(o).__name__} jump {step}")
                self.assertEqual(len(calls), 0, f"{type(o).__name__}: a move recomputed the box")
            finally:
                o.destroy()

    def test_a_shape_change_after_moves_recomputes(self):
        o = Rect(center=(0, 0), width=30, height=10)
        try:
            CV._cull_box(o)
            o.move_by(5, 5)
            o.angle = 45                       # not a move: a fresh box
            assert_hugs(self, CV._cull_box(o), CV._cull_box_full(o), "turn after move")
            o.move_by(5, 5)
            o.width = 90
            assert_hugs(self, CV._cull_box(o), CV._cull_box_full(o), "resize after move")
        finally:
            o.destroy()

    def test_perimeter_circle_is_not_shifted(self):
        """Center and perimeter point: a center write changes the radius."""
        from scena.shapes import CircleModel
        o = Circle(center=(0, 0), perimeter_point=(10, 0))
        try:
            self.assertEqual(o.model, CircleModel.CENTER_PERIMETER)
            CV._cull_box(o)
            for k in range(5):
                o.center = (float(k * 3), 0.0)
                assert_hugs(self, CV._cull_box(o), CV._cull_box_full(o), f"step {k}")
        finally:
            o.destroy()


class TestPlayingClip(unittest.TestCase):
    def test_a_playing_clip_keys_on_the_cell(self):
        """The box follows the cell on show; it is reused while the cell holds."""
        from scena import clock
        # Cells of different sizes: a box kept past a cell change is wrong.
        space = os.path.join(MEDIA, "space")
        sheet = Sheet(anchor="bottom", pixel_size=0.5)
        sheet.strip("run", [os.path.join(space, f) for f in
                            ("laserRed01.png", "ufoYellow.png", "star_gold.png")], fps=12)
        sheet.strip("idle", os.path.join(NINJA, "Idle__*.png"), fps=8)
        o = Sprite(sheet, center=(0, 0))
        try:
            o.play("run")
            real = CV._cull_box_full
            computed = steps = 0
            for k in range(90):
                clock.advance(1.0 / 60.0)
                if k % 3 == 0:
                    o.move_by(4.0, 0.0)
                if k == 45:
                    o.play("idle")
                calls = []
                with mock.patch.object(CV, "_cull_box_full", lambda x: calls.append(1) or real(x)), \
                        mock.patch.object(CV, "_cull_verify", lambda: False):
                    got = CV._cull_box(o)
                assert_hugs(self, got, real(o), f"step {k} cell {o._current_frame_index()}")
                computed += bool(calls)
                steps += 1
            self.assertLess(computed, steps // 2, "the box was recomputed on most frames")
        finally:
            o.destroy()


class TestSpriteDrawBox(unittest.TestCase):
    """``Sprite._draw_aabb`` holds every pixel the blit paints: the cell on
    show (cells of different sizes), offset, flips, heading, tilt, scale."""

    W, H = 400, 300

    def drawn_bbox(self, o):
        import numpy as np
        import skia
        eng = sys.modules["scena.canvas"].ScenaCanvas.get_current()
        surf = skia.Surface(self.W, self.H)
        saved = eng.skia_canvas
        eng.skia_canvas = surf.getCanvas()
        eng.skia_canvas.clear(skia.Color4f(0, 0, 0, 0))
        try:
            eng._draw_object(o)
        finally:
            eng.skia_canvas = saved
        a = np.asarray(surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))
        ys, xs = np.nonzero(a[..., 3] > 0)
        if not len(xs):
            return None
        return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)

    def sheet(self):
        space = os.path.join(MEDIA, "space")
        sh = Sheet(anchor="bottom", pixel_size=0.5)
        sh.strip("mix", [os.path.join(space, f) for f in
                         ("laserRed01.png", "ufoYellow.png", "star_gold.png")], fps=12)
        return sh

    def test_drawn_pixels_inside_the_box(self, draw_box=None):
        from scena import clock
        import random as _r
        r = _r.Random(8)
        checked = 0
        for case in range(40):
            o = Sprite(self.sheet(), center=(200.0, 150.0))
            try:
                o.play("mix")
                o.flip_x = r.random() < 0.5
                o.flip_y = r.random() < 0.3
                o.angle = r.choice((0.0, 30.0, 90.0, r.uniform(-180, 180)))
                o.scale = r.choice((0.7, 1.0, 1.6))
                o.offset = (r.uniform(-15, 15), r.uniform(-15, 15))
                if r.random() < 0.5:
                    o.tilt = r.uniform(-40, 40)
                for k in range(3):
                    clock.advance(1.0 / 12.0)
                    got = self.drawn_bbox(o)
                    if got is None:
                        continue
                    box = (draw_box or Sprite._draw_aabb)(o)
                    ctx = f"case {case} cell {o._current_frame_index()}"
                    self.assertLessEqual(box[0], got[0] + 1, ctx)
                    self.assertLessEqual(box[1], got[1] + 1, ctx)
                    self.assertGreaterEqual(box[2], got[2] - 1, ctx)
                    self.assertGreaterEqual(box[3], got[3] - 1, ctx)
                    checked += 1
            finally:
                o.destroy()
        self.assertGreater(checked, 80)

    def test_canary_the_box_sized_at_play(self):
        """The old box (``_oriented_frame``: the size from ``play()``) is caught."""
        def oriented(o):
            cx, cy, w, h, ang = o._oriented_frame()
            return CV._aabb_from_oriented(cx, cy, w, h, ang)
        with self.assertRaises(AssertionError):
            self.test_drawn_pixels_inside_the_box(draw_box=oriented)


class TestCanary(unittest.TestCase):
    def test_a_resize_counted_as_a_move_is_caught(self):
        """Every revision read as a move: a resized body keeps its old box."""
        real = CV._cull_box

        def all_moves(obj):
            cell = obj.__dict__.get("_pose_cell")
            hit = obj.__dict__.get("_cull_cache")
            if cell is not None and hit is not None and hit[2] is not None:
                cell[4] = hit[2][1] + (cell[0] - hit[0][0])
            return real(obj)

        case = TestCachedEqualsComputed("test_random_bodies_and_operations")
        with mock.patch.object(CV, "_cull_box", all_moves), \
                mock.patch.object(CV, "_cull_verify", lambda: False):
            with self.assertRaises(AssertionError):
                case.test_random_bodies_and_operations()

    def test_a_key_without_the_look_is_caught(self):
        real = CV._cull_cache_key

        def no_look(obj):
            k = real(obj)
            return None if k is None else (k[0], 0) + k[2:]      # the look never moves

        case = TestCachedEqualsComputed("test_random_bodies_and_operations")
        with mock.patch.object(CV, "_cull_cache_key", no_look), \
                mock.patch.object(CV, "_cull_verify", lambda: False):
            with self.assertRaises(AssertionError):
                case.test_random_bodies_and_operations()


if __name__ == "__main__":
    unittest.main()
