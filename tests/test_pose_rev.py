"""A body's pose revision moves whenever its collision pose key moves.

Rule under test (Collision Design.md, "Pose revision"): every write that can
change what a trusted body's pose key reads bumps ``_pose_rev`` on its root
(``state.bump_pose_rev``), so ``_update_proxy`` may keep a proxy whose
revision did not move without building the key. Trusted: plain Sprites,
Rect / Square, Circle, Ellipse, RegularPolygon and Triangle (every model)
with no link, anchor or pull owner on them or their Defining parts, and no
``hitbox_source="each"``. Any other body, or a
linked one, builds the key every time.

The oracle is the generic key: over random sequences of every public pose
operation, a revision that did not move means the key did not move.
``SCENA_VERIFY_POSE_REV=1`` (set by ``run_tiers`` for every tier) makes every
skip check the same thing across the whole suite.

Bug class guarded: a pose writer that forgets the bump (a stale hull: the
body collides where it was).
"""
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena import st
from scena.collision import get_collision_system, reset_collision_system
from scena.shapes import Circle, Ellipse, Rect, RegularPolygon, Square, Triangle
from scena.sprite import Sheet, Sprite
from scena.state import DerivedAttributeError
from scena.text import Text

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
SH = sys.modules["scena.shapes"]
MEDIA = os.path.join(ROOT, "examples", "media")
TILE = os.path.join(MEDIA, "tilesets", "Tiles", "2.png")
NINJA = os.path.join(MEDIA, "ninja")


def key(s):
    with mock.patch.object(C, "_SPRITE_POSE_KEY_FAST", False):
        return C._collision_pose_key(s)


class RevCase(unittest.TestCase):
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


def make(r, kind):
    x, y = r.uniform(-300, 300), r.uniform(-300, 300)
    if kind == "rect":
        return Rect(center=(x, y), width=r.uniform(5, 60), height=r.uniform(5, 60))
    if kind == "square":
        return Square(center=(x, y), length=r.uniform(5, 60))
    if kind == "circle":
        return Circle(center=(x, y), radius=r.uniform(3, 30))
    if kind == "ellipse":
        return Ellipse(center=(x, y), width=r.uniform(10, 60), height=r.uniform(5, 40))
    if kind == "tile":
        return Sprite(TILE, size=r.choice((32.0, 64.0)), center=(x, y))
    if kind in ("regular", "triangle"):
        cls = RegularPolygon if kind == "regular" else Triangle
        kw = {"n": r.choice((3, 5, 6))} if kind == "regular" else {"base_ratio": r.uniform(0.3, 1.5)}
        model = r.choice(("radius", "side", "vertex"))
        if model == "radius":
            return cls(center=(x, y), radius=r.uniform(4, 30), angle=r.uniform(-180, 180), **kw)
        if model == "side":
            return cls(center=(x, y), side=r.uniform(4, 40), **kw)
        return cls(vertex=(x, y), side=r.uniform(4, 40), angle=r.uniform(-180, 180), **kw)
    sheet = Sheet(anchor="bottom", pixel_size=0.2)
    sheet.strip("run", os.path.join(NINJA, "Run__*.png"), fps=12)
    sheet.strip("idle", os.path.join(NINJA, "Idle__*.png"), fps=8)
    s = Sprite(sheet, center=(x, y), hitbox_shape=r.choice(("rect", "auto", "circle")),
               hitbox_source=r.choice(("clip", "all")))
    s.play("run")
    return s


def operate(r, s, kind):
    """One random public pose operation; returns its name."""
    ops = ["move_by", "move_to", "center", "center.x", "angle", "rotate_by", "scale",
           "flip_x", "flip_y", "noop"]
    if kind in ("rect", "ellipse", "tile", "sheet"):
        ops += ["width", "height"]
    if kind == "circle":
        ops += ["radius"]
    if kind in ("regular", "triangle"):
        ops += ["radius", "side", "vertex", "vertex.y"]
    if kind == "triangle":
        ops += ["base_ratio"]
    if kind in ("tile", "sheet"):
        ops += ["offset", "hitbox_scale", "art_angle"]
    if kind == "sheet":
        ops += ["play", "advance"]
    op = r.choice(ops)
    try:
        _apply(r, s, op)
    except DerivedAttributeError:
        op += " (refused)"          # a Derivate input of this model: no write
    return op


def _apply(r, s, op):
    if op == "move_by":
        s.move_by(r.uniform(-20, 20), r.uniform(-20, 20))
    elif op == "move_to":
        s.move_to(r.uniform(-300, 300), r.uniform(-300, 300))
    elif op == "center":
        s.center = (r.uniform(-300, 300), r.uniform(-300, 300))
    elif op == "center.x":
        s.center.x = r.uniform(-300, 300)
    elif op == "angle":
        s.angle = r.choice((0.0, 30.0, 90.0, 180.0, r.uniform(-180, 180)))
    elif op == "rotate_by":
        s.rotate_by(r.uniform(-45, 45))
    elif op == "scale":
        s.scale = r.choice((0.5, 1.0, 1.5))
    elif op == "flip_x":
        s.flip_x = not s.flip_x
    elif op == "flip_y":
        s.flip_y = not s.flip_y
    elif op == "width":
        s.width = r.uniform(5, 80)
    elif op == "height":
        s.height = r.uniform(5, 80)
    elif op == "radius":
        s.radius = r.uniform(3, 40)
    elif op == "side":
        s.side = r.uniform(3, 40)
    elif op == "vertex":
        s.vertex = (r.uniform(-300, 300), r.uniform(-300, 300))
    elif op == "vertex.y":
        s.vertex.y = r.uniform(-300, 300)
    elif op == "base_ratio":
        s.base_ratio = r.uniform(0.2, 1.8)
    elif op == "offset":
        s.offset = (r.uniform(-10, 10), r.uniform(-10, 10))
    elif op == "hitbox_scale":
        s.hitbox.scale = r.choice((1.0, 0.6, (0.5, 0.9)))
    elif op == "art_angle":
        s.art_angle = r.choice((0.0, 90.0, 270.0))
    elif op == "play":
        s.play(r.choice(("run", "idle")))
    elif op == "advance":
        from scena import clock
        clock.advance(r.uniform(0.02, 0.3))
        C._sync_auto_hitbox_frame(s)


class TestRevisionCoversTheKey(RevCase):
    def test_random_operations_on_every_trusted_kind(self):
        checked = trusted = 0
        for seed in range(30):
            r = random.Random(seed)
            for kind in ("rect", "square", "circle", "ellipse", "tile", "sheet",
                         "regular", "triangle"):
                s = self.track(make(r, kind))
                for k in range(12):
                    rev0 = C._pose_rev_of(s)
                    key0 = key(s)
                    op = operate(r, s, kind)
                    rev1 = C._pose_rev_of(s)
                    key1 = key(s)
                    if rev0 is not None:
                        trusted += 1
                    if rev0 is not None and rev0 == rev1:
                        self.assertEqual(key1, key0, f"seed {seed} {kind} op {k} {op}: key moved, "
                                                      f"revision {rev0} did not")
                    checked += 1
                s.destroy()
        self.assertGreater(trusted, checked * 0.9, "most plain bodies must be trusted")


class TestTrust(RevCase):
    def test_links_text_and_each_are_not_trusted(self):
        st.px = 3.0
        a = self.track(Rect(center=(0, 0), width=10, height=10))
        self.assertIsNotNone(C._pose_rev_of(a))
        a.center["x"] @= lambda: st.px
        self.assertIsNone(C._pose_rev_of(a), "a linked center is pulled, not written")
        b = self.track(Rect(center=(0, 0), width=10, height=10))
        b["width"] @= lambda: st.px * 4
        self.assertIsNone(C._pose_rev_of(b), "a linked width is pulled, not written")
        t = Text("hi", center=(0, 0))
        self.owned.append(t)
        self.assertIsNone(C._pose_rev_of(t), "Text lays out on read")
        sheet = Sheet(anchor="bottom", pixel_size=0.2)
        sheet.strip("run", os.path.join(NINJA, "Run__*.png"), fps=12)
        e = self.track(Sprite(sheet, center=(0, 0), hitbox_source="each"))
        self.assertIsNone(C._pose_rev_of(e), "hitbox_source='each' re-fits per cell")

    def test_radial_polygons_are_trusted_until_linked(self):
        st.pr = 7.0
        for s in (self.track(Triangle(center=(0, 0), radius=9, base_ratio=0.5)),
                  self.track(RegularPolygon(n=5, vertex=(0, 0), side=8))):
            self.assertIsNotNone(C._pose_rev_of(s), type(s).__name__)
        t = self.track(Triangle(center=(0, 0), radius=9))
        t["base_ratio"] @= lambda: st.pr / 10
        self.assertIsNone(C._pose_rev_of(t), "a linked base_ratio is pulled, not written")

        class Pointy(Triangle):
            def _collision_pose_extra(self):
                return ()
        p = self.track(Pointy(center=(0, 0), radius=9))
        self.assertIsNone(C._pose_rev_of(p), "a subclass with its own pose hook")


class TestSkip(RevCase):
    def test_a_still_trusted_body_builds_no_key(self):
        s = self.track(Sprite(TILE, size=64, center=(0, 0), group="chao"))
        cs = get_collision_system()
        col = C.ensure_collider(s)
        cs._update_proxy(col, commit_motion=False)
        with mock.patch.object(C, "_collision_pose_key", side_effect=AssertionError("built")):
            with mock.patch.object(C, "_POSE_REV_VERIFY", False):
                self.assertTrue(cs._update_proxy(col, commit_motion=False))
        s.move_by(5, 0)
        calls = []
        real = C._collision_pose_key
        with mock.patch.object(C, "_collision_pose_key", side_effect=lambda x: calls.append(1) or real(x)):
            cs._update_proxy(col, commit_motion=False)
        self.assertTrue(calls, "a moved body builds its key")


class TestCanary(RevCase):
    def test_a_forgotten_bump_is_caught(self):
        """The A1 float funnel without its (inline) bump: moves go unseen."""
        def no_bump(point, x=None, y=None):
            changed = False
            d = point.__dict__
            if x is not None and d.get('x') != float(x):
                d['x'] = float(x)
                changed = True
            if y is not None and d.get('y') != float(y):
                d['y'] = float(y)
                changed = True
            return changed

        case = TestRevisionCoversTheKey("test_random_operations_on_every_trusted_kind")
        case.setUp()
        try:
            with mock.patch.object(SH, "_takein_xy_float", no_bump):
                with self.assertRaises(AssertionError):
                    case.test_random_operations_on_every_trusted_kind()
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
