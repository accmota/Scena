"""A Sprite's collision pose key, read the short way, is the same tuple.

Rule under test (Collision Design.md, "World prims / pose keys"): the pose key
of a Sprite is ``(epoch, x, y, draw angle, scale, hitbox scale x / y, hitbox
w / h, flip x / y, offset x / y)``. ``_sprite_pose_key_fast`` builds it from the
instance fields directly, and only where a field read would return the stored
value anyway (no anchor, no link, already classified bare); anywhere else it
answers ``None`` and the generic ``_collision_pose_key`` runs. The oracle is
equality with the generic key over sprite states: scale, flips, art angle,
rotation, offset, hitbox scale and anchor, clips with each hitbox source,
linked width / center / angle, size writes.

Bug class guarded: a fast key that misses an input (a stale prim slides or
keeps its old size) or that reads a linked value without pulling it.
"""
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena.collision import get_collision_system, reset_collision_system
from scena.sprite import Sheet, Sprite
from scena import st

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
MEDIA = os.path.join(ROOT, "examples", "media")
TILE = os.path.join(MEDIA, "tilesets", "Tiles", "2.png")
NINJA = os.path.join(MEDIA, "ninja")


def generic(s):
    with mock.patch.object(C, "_SPRITE_POSE_KEY_FAST", False):
        return C._collision_pose_key(s)


class PoseKeyCase(unittest.TestCase):
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

    def track(self, s):
        self.owned.append(s)
        C.ensure_collider(s)
        return s

    def agree(self, s, ctx, expect_fast=True):
        fast = C._sprite_pose_key_fast(s)
        slow = generic(s)
        if fast is None:
            self.assertFalse(expect_fast, f"{ctx}: the fast key declined a plain sprite")
        else:
            self.assertEqual(fast, slow, ctx)
        self.assertEqual(C._collision_pose_key(s), slow, ctx + " (dispatch)")


class TestPlainSprites(PoseKeyCase):
    def test_random_poses(self):
        r = random.Random(4)
        sheet = Sheet(anchor="bottom", pixel_size=0.2)
        sheet.strip("run", os.path.join(NINJA, "Run__*.png"), fps=12)
        sheet.strip("idle", os.path.join(NINJA, "Idle__*.png"), fps=8)
        for i in range(120):
            source = None
            if r.random() < 0.5:
                s = self.track(Sprite(TILE, size=r.choice((32.0, 64.0)), center=(r.uniform(-500, 500), 0)))
            else:
                source = r.choice((None, "clip", "all", "each"))
                kw = {} if source is None else {"hitbox_source": source}
                s = self.track(Sprite(sheet, center=(r.uniform(-500, 500), 0),
                                      hitbox_shape=r.choice(("rect", "auto", "hull", "circle")),
                                      hitbox_anchor=r.choice(("center", "bottom")),
                                      hitbox_scale=r.choice((1.0, 0.6, (0.5, 0.9))), **kw))
                s.play(r.choice(("run", "idle")))
            for k in range(6):
                op = r.random()
                if op < 0.2:
                    s.scale = r.choice((0.5, 1.0, 1.7, 0.0, 2.25))
                elif op < 0.35:
                    s.flip_x = not s.flip_x
                elif op < 0.45:
                    s.flip_y = not s.flip_y
                elif op < 0.6:
                    s.angle = r.uniform(-180, 180)
                elif op < 0.7:
                    s.width = r.uniform(10, 90)
                elif op < 0.75:
                    s.move_by(r.uniform(-30, 30), r.uniform(-30, 30))
                elif op < 0.82:
                    s.offset = (r.uniform(-12, 12), r.uniform(-12, 12))
                else:
                    s.center = (r.uniform(-500, 500), r.uniform(-50, 50))
                if r.random() < 0.3:
                    from scena import clock
                    clock.advance(0.09)               # the playhead moves (each: rebake)
                    C._sync_auto_hitbox_frame(s)
                self.agree(s, f"sprite {i} op {k} source {source}", expect_fast=source != "each")
            s.destroy()


class TestLinkedFallBack(PoseKeyCase):
    """A linked input never takes the raw read; the key still matches."""

    def test_linked_width_center_and_angle(self):
        st.w = 40.0
        st.x = 10.0
        st.a = 0.0
        s = self.track(Sprite(TILE, size=64.0, center=(0, 0)))
        s["width"] @= lambda: st.w
        self.agree(s, "linked width", expect_fast=False)
        st.w = 80.0
        self.agree(s, "linked width moved", expect_fast=False)
        t = self.track(Sprite(TILE, size=64.0, center=(0, 0)))
        t.center["x"] @= lambda: st.x
        st.x = 120.0
        self.agree(t, "linked center", expect_fast=False)
        u = self.track(Sprite(TILE, size=64.0, center=(0, 0)))
        u["angle"] @= lambda: st.a
        st.a = 33.0
        self.agree(u, "linked angle", expect_fast=False)


class TestCanary(PoseKeyCase):
    def test_a_missing_input_is_caught(self):
        real = C._sprite_pose_key_fast

        def no_flip_y(s):
            k = real(s)
            return None if k is None else k[:10] + (0.0,) + k[11:]

        case = TestPlainSprites("test_random_poses")
        case.setUp()
        try:
            with mock.patch.object(C, "_sprite_pose_key_fast", no_flip_y):
                with self.assertRaises(AssertionError):
                    case.test_random_poses()
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
