"""The cached cull box equals the computed one.

Rule under test (Canvas Design.md, "Offscreen culling", the cache): a body
whose pose revision is trusted keeps its padded cull box until its pose
revision, its look revision (every paint write) or, for a Sprite, its sheet
layout moves. A transient, a custom cull pad or a playing clip skip the cache.
``canvas._CULL_CACHE = False`` computes every box (the oracle).

Random bodies go through random pose and paint operations; after each, the
box the cull uses equals ``_cull_box_full``.

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
                    self.assertEqual(got, CV._cull_box_full(o), f"body {i} {kind} op {k} {op}")
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


class TestCanary(unittest.TestCase):
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
