"""The cached blit plan draws what a fresh blit draws.

Rule under test (Sprite Design.md, "Blit plan cache"): a Sprite keeps the
geometry of its blit (center, local matrix, source and destination rects)
while its trusted pose revision, the cell on show, the sheet and its layout
epoch hold. The paint is read live, so paint writes keep the plan. A revision
that moved only by moves of the marked center keeps the plan at the new
center. ``sprite._BLIT_PLAN = False`` never stores a plan (the oracle).

Random sprites go through random pose, paint, clip and link operations; after
each, the sprite is drawn twice (the second draw reads the plan when one was
stored) and every draw is pixel-identical to a fresh blit of the same state.
Verify mode recomputes every plan it uses, a second oracle.

Bug class guarded: a cache keyed on less than it reads (R5 / GR7 in Testing
Design): a write that changes how a sprite draws without moving its pose
revision, which would draw it where it was.
"""
import itertools
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import skia

from scena import clock, st
from scena.sprite import Sheet, Sprite
from scena.state import LinkedAttributeError

SP = sys.modules["scena.sprite"]
CO = sys.modules["scena.collision"]
ENT = sys.modules["scena.entity"]
MEDIA = os.path.join(ROOT, "examples", "media")
TILE = os.path.join(MEDIA, "tilesets", "Tiles", "2.png")
NINJA = os.path.join(MEDIA, "ninja")
SPACE = os.path.join(MEDIA, "space")
W, H = 240, 180
_NAMES = itertools.count()


def pixels(o, plan):
    """``o``'s blit on a fresh raster: ``plan=False`` is a fresh blit that
    stores nothing; ``plan=True`` is the normal path (reads or stores)."""
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(skia.Color4f(0, 0, 0, 0))
    c.translate(W / 2, H / 2)
    c.scale(1.5, -1.5)                       # y-up, a camera-like zoom
    if plan:
        o._blit_plain(c)
    else:
        saved = o._blit_plan
        object.__setattr__(o, "_blit_plan", None)
        with mock.patch.object(SP, "_BLIT_PLAN", False):
            o._blit_plain(c)
        object.__setattr__(o, "_blit_plan", saved)
    return np.asarray(surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))


def mixed_sheet():
    sh = Sheet(anchor="bottom", pixel_size=0.5)
    sh.strip("mix", [os.path.join(SPACE, f) for f in
                     ("laserRed01.png", "ufoYellow.png", "star_gold.png")], fps=12)
    return sh


def make(r):
    k = r.choice(("tile", "ninja", "mixed"))
    x, y = r.uniform(-40, 40), r.uniform(-30, 30)
    if k == "tile":
        return k, Sprite(TILE, size=r.choice((24.0, 40.0)), center=(x, y))
    if k == "ninja":
        sheet = Sheet(anchor="bottom", pixel_size=0.08)
        sheet.strip("run", os.path.join(NINJA, "Run__*.png"), fps=12)
        sheet.strip("idle", os.path.join(NINJA, "Idle__*.png"), fps=8)
        return k, Sprite(sheet, center=(x, y))
    return k, Sprite(mixed_sheet(), center=(x, y), height=40)


OPS = ("move", "move_to", "turn", "angle", "scale", "flip_x", "flip_y", "offset", "art_angle",
       "tilt", "width", "height", "alpha", "blend", "hue", "gray", "visible", "play", "stop",
       "frame", "clip_offset", "link", "time")


def operate(r, o, kind):
    op = r.choice(OPS)
    try:
        if op == "move":
            o.move_by(r.uniform(-9, 9), r.uniform(-9, 9), force=True)
        elif op == "move_to":
            o.center = (r.uniform(-40, 40), r.uniform(-30, 30))
        elif op == "turn":
            o.rotate_by(r.uniform(-60, 60), force=True)
        elif op == "angle":
            o.angle = r.choice((0.0, 90.0, r.uniform(-180, 180)))
        elif op == "scale":
            o.scale = r.choice((0.5, 1.0, 1.7))
        elif op == "flip_x":
            o.flip_x = not o.flip_x
        elif op == "flip_y":
            o.flip_y = not o.flip_y
        elif op == "offset":
            o.offset = (r.uniform(-8, 8), r.uniform(-8, 8))
        elif op == "art_angle":
            o.art_angle = r.choice((0.0, 90.0, 45.0))
        elif op == "tilt":
            o.tilt = r.uniform(-30, 30)
        elif op == "width":
            o.width = r.uniform(10, 60)
        elif op == "height":
            o.height = r.uniform(10, 60)
        elif op == "alpha":
            o.set_alpha(r.choice((0.3, 1.0)))
        elif op == "blend":
            o.blend = r.choice(("normal", "add", "multiply"))
        elif op == "hue":
            o.hue = r.choice((0, 120))
        elif op == "gray":
            o.gray = r.choice((0.0, 1.0))
        elif op == "visible":
            o.visible = not o.visible
        elif op == "play" and kind != "tile":
            o.play(r.choice(("run", "idle")) if kind == "ninja" else "mix")
        elif op == "stop" and kind != "tile":
            o.stop()
        elif op == "frame" and kind != "tile":
            o.stop()
            o.frame = r.randint(0, 2)
        elif op == "clip_offset" and kind != "tile":
            name = f"nudge{next(_NAMES)}"
            o._sheet.clip(name, [0, 1], offset=(r.uniform(-6, 6), r.uniform(-6, 6)))
            o.play(name)
        elif op == "link" and not o.center["x"].is_linked:
            st.bx = r.uniform(-30, 30)
            o.center["x"] @= lambda: st.bx
        elif op == "time":
            clock.advance(1.0 / 12.0)
    except (TypeError, ValueError, AttributeError, LinkedAttributeError):
        pass                          # a refusal is fine: the drawing must still agree
    return op


class TestPlanEqualsFresh(unittest.TestCase):
    def run_program(self, seed=5, bodies=60, steps=12):
        r = random.Random(seed)
        hits = checked = 0
        owned = []
        try:
            for i in range(bodies):
                kind, o = make(r)
                owned.append(o)
                for k in range(steps):
                    op = operate(r, o, kind)
                    if r.random() < 0.3:
                        st.bx = r.uniform(-30, 30)       # moves a linked body, no write
                    for draw in range(2):
                        planned = o._blit_plan is not None
                        got = pixels(o, plan=True)
                        want = pixels(o, plan=False)
                        diff = int(np.abs(got.astype(int) - want.astype(int)).max())
                        self.assertEqual(diff, 0, f"body {i} {kind} op {k} {op} draw {draw}: "
                                                  f"cached blit differs by {diff}/255")
                        checked += 1
                        hits += planned and o._blit_plan is not None
        finally:
            for o in owned:
                o.destroy()
        return hits, checked

    def test_random_sprites_and_operations(self):
        hits, checked = self.run_program()
        self.assertGreater(hits, checked // 4, "the plan must be used")

    def test_verify_mode_agrees(self):
        """Every plan used equals a fresh one (verify mode raises otherwise)."""
        with mock.patch.object(CO, "_POSE_REV_VERIFY", True):
            self.run_program(seed=11, bodies=30)


class TestPlanUse(unittest.TestCase):
    def test_a_still_sprite_reads_the_plan(self):
        o = Sprite(TILE, size=32.0, center=(5, 5))
        try:
            pixels(o, plan=True)
            pixels(o, plan=True)
            self.assertIsNotNone(o._blit_plan)
            with mock.patch.object(Sprite, "_blit_geometry", side_effect=AssertionError("computed")), \
                    mock.patch.object(SP, "_plan_verify", lambda: False):
                pixels(o, plan=True)
        finally:
            o.destroy()

    def test_a_paint_write_keeps_the_plan(self):
        o = Sprite(TILE, size=32.0, center=(5, 5))
        try:
            pixels(o, plan=True)
            pixels(o, plan=True)
            plan = o._blit_plan
            o.set_alpha(0.5)
            o.hue = 90
            pixels(o, plan=True)
            self.assertIs(o._blit_plan, plan)
        finally:
            o.destroy()

    def test_a_mover_from_birth_keeps_a_plan(self):
        """A body that only moves (a shot) is drawn from its plan at each new
        center, never recomputed, and matches a fresh blit."""
        o = Sprite(TILE, size=24.0, center=(-60, 0))
        try:
            o.angle = 30
            calls = []
            real = Sprite._blit_geometry
            for step in range(20):
                o.move_by(5.25, 1.5)
                with mock.patch.object(Sprite, "_blit_geometry",
                                       lambda s, i: calls.append(step) or real(s, i)), \
                        mock.patch.object(SP, "_plan_verify", lambda: False):
                    got = pixels(o, plan=True)
                self.assertTrue(np.array_equal(got, pixels(o, plan=False)), f"step {step}")
            self.assertLessEqual(len(calls), 2, f"a move recomputed the plan: {calls}")
        finally:
            o.destroy()

    def test_a_turning_body_is_not_planned(self):
        """A heading change every frame: no plan, no store, fresh pixels."""
        o = Sprite(TILE, size=24.0, center=(0, 0))
        try:
            for step in range(10):
                o.rotate_by(7.0, force=True)
                got = pixels(o, plan=True)
                self.assertIsNone(o._blit_plan, f"step {step}")
                self.assertTrue(np.array_equal(got, pixels(o, plan=False)), f"step {step}")
        finally:
            o.destroy()

    def test_a_linked_center_is_never_planned(self):
        st.lx = 0.0
        o = Sprite(TILE, size=24.0, center=(0, 0))
        try:
            o.center["x"] @= lambda: st.lx
            for step in range(6):
                st.lx = step * 4.0                  # moves with no write
                got = pixels(o, plan=True)
                self.assertIsNone(o._blit_plan)
                self.assertTrue(np.array_equal(got, pixels(o, plan=False)), f"step {step}")
        finally:
            o.destroy()


class _Any:
    """Equal to everything; ``x - _Any()`` is ``_Any()`` too."""
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    def __ge__(self, other):
        return True

    def __rsub__(self, other):
        return self

    __hash__ = object.__hash__


class TestCanary(unittest.TestCase):
    def canary(self, patch_store=None, patches=()):
        real = Sprite._store_blit_plan

        def store(s, idx, sheet, geo, cell):
            real(s, idx, sheet, geo, cell)
            plan = s._blit_plan
            if plan is not None and patch_store is not None:
                object.__setattr__(s, "_blit_plan", patch_store(plan))

        case = TestPlanEqualsFresh("test_random_sprites_and_operations")
        with mock.patch.object(Sprite, "_store_blit_plan", store), \
                mock.patch.object(SP, "_plan_verify", lambda: False):
            for target, name, value in patches:
                self.enterContext(mock.patch.object(target, name, value))
            with self.assertRaises(AssertionError):
                case.run_program(seed=5, bodies=60)

    def test_a_key_without_the_cell_is_caught(self):
        self.canary(lambda p: p[:2] + (_Any(),) + p[3:])

    def test_a_key_without_the_layout_epoch_is_caught(self):
        self.canary(lambda p: p[:4] + (_Any(),) + p[5:])

    def test_every_revision_read_as_a_move_is_caught(self):
        self.canary(lambda p: (p[0], _Any()) + p[2:])

    def test_a_pose_write_that_does_not_bump_is_caught(self):
        """``offset`` / ``art_angle`` writes without a pose bump."""
        self.canary(patches=((ENT, "bump_pose_rev", lambda obj: None),))


if __name__ == "__main__":
    unittest.main()
