"""Caches of the 2026-10 performance work answer like the full computation.

Found by the review of groups A and B (2026-10-12): each test is one gap
where a cached or skipped answer outlived what it was built from. Rules under
test: Collision Design.md, "Pose revision", "Moved set and vectorized
candidates", "Shared partner lists", "Step cost"; Canvas Design.md,
"Offscreen culling" (the cache, the shift, the plan); Effect System Design.md
§5.5.

Bug class guarded: a writer, a clock or a structure change that a cache does
not see (a pose input written with no revision bump, a moved set drained too
early, a collider no revision cell reaches, a partner list a retag cannot
reach, a cull that changes how the drawn objects batch).
"""
import os
import sys
import unittest
import warnings
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import skia

from scena import Blur, CheapGlow, Extrude, GlowFilter, Halo, Rim, Shield, clock, collide, group, st
from scena.collision import (
    STATIC, Collider, TouchingContact, collide_exit, get_collision_system,
    reset_collision_system, resolve,
)
from scena.scenamath import Vec2
from scena.shapes import Circle, Rect
from scena.sprite import Sheet, Sprite

from tests.hypothesis_support import quiet
from tests.system_support import system_world
from tests.floor_support import with_floor  # noqa: E402

C = sys.modules["scena.collision"]
CV = sys.modules["scena.canvas"]
MEDIA = os.path.join(ROOT, "examples", "media")
TILE = os.path.join(MEDIA, "tilesets", "Tiles", "2.png")
NINJA = os.path.join(MEDIA, "ninja")
SPACE = os.path.join(MEDIA, "space")


def ninja_sheet(anchor="center"):
    sheet = Sheet(anchor=anchor, pixel_size=0.2)
    sheet.strip("run", os.path.join(NINJA, "Run__*.png"), fps=12)
    sheet.strip("idle", os.path.join(NINJA, "Idle__*.png"), fps=8)
    return sheet


class _Collision(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")
        reset_collision_system()
        self.cs = get_collision_system()
        self.made = []

    def tearDown(self):
        for o in self.made:
            try:
                o.destroy()
            except Exception:
                pass
        reset_collision_system()

    def keep(self, o):
        self.made.append(o)
        return o


class TestPoseWriters(_Collision):
    """Every pose input written moves the pose revision (B1)."""

    def test_a_vector_part_write_moves_the_hull(self):
        # Vec2._takein overrides the funnel that bumps (as Point's did).
        for how in ("=", "<<", ".x ="):
            reset_collision_system()
            self.cs = get_collision_system()
            a = self.keep(Rect(p1=(0, 0), vec=(10, 10), group="a"))
            b = self.keep(Rect(center=(60, 5), width=10, height=10, group="b"))
            log = []

            @collide("a", "b")
            def _hit(x, y):
                log.append("hit")

            self.cs.step()
            if how == "=":
                a.vec = (70, 10)
            elif how == "<<":
                a.vec << (70, 10)
            else:
                a.vec.x = 70
            self.cs.step()
            self.assertGreaterEqual(a._collider._proxy[2], 70.0, how)
            self.assertEqual(log, ["hit"], how)
            a.destroy()
            b.destroy()

    def test_a_lazy_bake_moves_the_revision(self):
        # A "clip" sprite enrolled on a later clip: the bake sets the hitbox
        # size the pose key reads; verify mode raised on the next step.
        g = self.keep(Sprite(ninja_sheet(), center=(0, 0), group="g",
                             hitbox_source="clip", hitbox_shape="rect"))
        g.play("idle")
        o = self.keep(Rect(center=(900, 0), width=10, height=10, group="o"))

        @collide("g", "o")
        def _p(a, b):
            pass

        with mock.patch.object(C, "_POSE_REV_VERIFY", True):
            for _ in range(3):
                self.cs.step()


class TestStepDrain(_Collision):
    """The step's moved set is taken after the prune and the linked hitbox
    refresh, whose writes belong to the same step."""

    def run_active(self, linked):
        log = []
        s = self.keep(Sprite(TILE, size=32.0, center=(0, 0), group="s"))
        c = self.keep(Rect(center=(0, 0), width=10, height=10, group="c"))

        @collide("s", "c")
        def _e(a, b):
            log.append("enter")

        @collide_exit("s", "c")
        def _x(a, b, i=None):
            log.append("exit")

        st.on_ = True
        if linked:
            s.hitbox["active"] @= lambda: st.on_
        seq = []
        for on in (True, True, False, False, True, True, False):
            if linked:
                st.on_ = on
            else:
                s.hitbox.active = on
            self.cs.step()
            seq.append((tuple(log), s._collider._proxy_valid))
            log.clear()
        s.destroy()
        c.destroy()
        return seq

    def test_a_linked_hitbox_active_acts_in_its_step(self):
        self.assertEqual(self.run_active(True), self.run_active(False))

    def test_a_move_by_a_prune_exit_handler_is_seen_in_its_step(self):
        log = []
        a = self.keep(Rect(center=(0, 0), width=10, height=10))
        b = self.keep(Circle(center=(8, 0), radius=4))
        body = Collider([a, b])
        self.keep(Rect(center=(0, 0), width=30, height=30, group="wall"))
        hero = self.keep(Rect(center=(500, 0), width=10, height=10, group="hero"))
        self.keep(Rect(center=(0, 400), width=10, height=10, group="coin"))

        def on_exit(me, other, info=None):
            hero.center = (0, 400)

        body.on_collide_exit = on_exit

        @collide("hero", "coin")
        def _got(h, c):
            log.append("coin")

        @collide("wall", "hero")
        def _w(a, b):
            pass

        self.cs.step()
        a.destroy()
        b.destroy()
        self.cs.step()                  # prunes the body: its exit moves the hero
        self.assertEqual(log, ["coin"])


class TestQueriesSeeEveryBody(_Collision):
    """A query between steps refreshes what can change with no write (a
    "clip" hitbox switched by time) and what no revision cell reaches."""

    def test_a_clip_switched_by_time_is_queried_fresh(self):
        g = self.keep(Sprite(ninja_sheet(), center=(0, 0), group="chao",
                             hitbox_source="clip", hitbox_shape="rect"))
        g.mass = STATIC
        g.play("idle", loops=1, next="run")
        self.keep(Rect(center=(900, 0), width=10, height=10, group="outro"))

        @collide("chao", "outro")
        def _p(a, b):
            pass

        self.cs.step()
        hero = self.keep(Rect(center=(31, 60), width=4, height=10, group="heroi"))
        hero.mass = 1.0
        clock.advance(3.0)              # "idle" ends; "run" (wider) plays
        got = hero.floor_below(group="chao", depth=200)     # first: the oracle refreshes
        with mock.patch.object(C, "_QUERY_VECTOR", False):
            want = hero.floor_below(group="chao", depth=200)
        self.assertIs(want, g)
        self.assertIs(got, want)

    def test_an_implicit_collider_a_collider_rebound_is_still_refreshed(self):
        log = []
        a = self.keep(Rect(center=(0, 0), width=10, height=10, group="a"))
        b = self.keep(Rect(center=(100, 0), width=10, height=10, group="b"))

        @collide("a", "b")
        def _hit(x, y):
            log.append("hit")

        self.cs.step()
        implicit = a._collider
        Collider([a])                   # takes a._collider; the implicit one stays
        self.cs.step()
        a.move_by(100, 0)
        self.cs.step()
        self.assertGreater(implicit._proxy[0], 90.0)
        self.assertIn("hit", log)


@with_floor
class TestPartnerLists(_Collision):
    """A formula group as a resolve side follows retags (H1's selective drop)."""

    def land(self, start_tagged):
        chao = self.keep(Rect(center=(0, -10), width=600, height=20, group="chao"))
        chao.mass = STATIC
        caixa = self.keep(Rect(center=(0, 100), width=200, height=20, group="caixa"))
        caixa.mass = STATIC
        hero = self.keep(Rect(center=(0, 300), width=20, height=40, group="z"))
        hero.mass = 1.0
        hero.vel = Vec2(0, 0)
        if start_tagged:
            hero.tag("a")
        self.keep(Rect(center=(5000, 0), width=10, height=10, group="sensor"))

        @collide("a", "sensor")
        def _h(a, s):
            pass

        group["inim_t"] @= lambda: group["a"]
        resolve("z", "chao", bounce=0.0)
        resolve(group["inim_t"], "caixa", bounce=0.0)
        self.cs.step()
        for f in range(120):
            if f == 2:
                if start_tagged:
                    hero.untag("a")
                else:
                    hero.tag("a")
            hero.vel.y -= 900 / 60
            hero.move_by(0, hero.vel.y / 60)
            self.cs.step()
            if "bottom" in hero.touching_sides:
                hero.vel.y = 0
        return float(hero.center.y) - 20

    def test_joining_the_formula_by_a_tag(self):
        self.assertAlmostEqual(self.land(False), 110.0, delta=0.5)

    def test_leaving_the_formula_by_an_untag(self):
        # Also the KeyError of the last member leaving (registry).
        self.assertAlmostEqual(self.land(True), 0.0, delta=0.5)

    def test_a_shared_list_tail_skips_its_owner(self):
        bodies = [self.keep(Rect(center=(i * 15.0, 0), width=20, height=20, group="e"))
                  for i in range(6)]
        for b in bodies:
            b.mass = 1.0
        resolve("e", "e", bounce=0.0)
        self.cs.step()
        ca = bodies[2]._collider
        with mock.patch.object(C, "_POOL_VECTOR_MIN", 2):
            pool = self.cs._resolve_pool(ca)
        it = self.cs._iter_near(ca, pool)
        got = [next(it)[0]]
        ca._proxy_valid = False         # the pass's "proxy went invalid" tail
        try:
            got += [p[0] for p in it]
        finally:
            ca._proxy_valid = True
        self.assertNotIn(ca, got)
        self.assertIn(bodies[5]._collider, got)


class TestSweepResidue(unittest.TestCase):
    def test_an_overlapping_start_with_residue_motion_hits(self):
        P, K = C.Prim, C.PrimKind
        tri = [(0, 0), (10, 0), (5, 8)]
        a = P(K.POLY, C._aabb_from_verts(tri), (), list(tri))
        b = P(K.OBB, C._aabb_from_obb(5, 3, 4, 4, 0.3), (5, 3, 4, 4, 0.3))
        for m in (1e-300, 1e-17, 1e-16):
            hit = C._toi_prim_sets([a], [b], m, m)
            self.assertIsNotNone(hit, m)
            self.assertEqual(hit[0], 0.0)


class TestColliderSubclass(_Collision):
    def test_a_callback_method_counts_as_set(self):
        log = []

        class Sub(Collider):
            def on_collide(self, me, other, info):
                log.append("sub")

        self.keep(Rect(center=(0, 0), width=30, height=30, group="wall"))
        self.keep(Rect(center=(900, 0), width=5, height=5, group="far"))

        @collide("wall", "far")         # enrolls the wall
        def _w(a, b):
            pass

        s = Sub([self.keep(Rect(center=(0, 0), width=10, height=10)),
                 self.keep(Circle(center=(5, 0), radius=4))])
        self.assertIn(C.ANYTHING, s._pair_targets)
        self.cs.step()
        self.assertIn("sub", log)

    def test_stay_and_exit_methods_are_called(self):
        log = []

        class Sub(Collider):
            def on_collide(self, me, other, info):
                log.append("enter")

            def on_collide_stay(self, me, other, info):
                log.append("stay")

            def on_collide_exit(self, me, other):
                log.append("exit")

        wall = self.keep(Rect(center=(0, 0), width=30, height=30))
        wall.collidable = True
        Sub([self.keep(Rect(center=(0, 0), width=10, height=10)),
             self.keep(Circle(center=(5, 0), radius=4))])
        self.cs.step()
        self.cs.step()
        wall.center = (900, 0)
        self.cs.step()
        self.assertEqual(log, ["enter", "stay", "exit"])

    def test_an_async_method_raises_at_the_class_line(self):
        """``on_collide = async_fn`` refuses at the assignment; the method
        spelling refuses at the class line (before: at the first contact)."""
        for name in ("on_collide", "on_collide_stay", "on_collide_exit"):
            async def cb(self, *a):
                pass
            with self.subTest(name=name), self.assertRaises(TypeError) as ctx:
                type("Sub", (Collider,), {name: cb})
            self.assertIn("cannot be async", str(ctx.exception))


# --------------------------------------------------------------------------
# Drawing: cull boxes and the batching plan
# --------------------------------------------------------------------------

def screen(w):
    from scena import canvas
    a = np.asarray(w.surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))
    return a[: int(canvas.height), : int(canvas.width)].copy()


def draw(w, cull):
    from scena import canvas
    saved = canvas.cull_offscreen
    canvas.cull_offscreen = cull
    try:
        w.fw._draw_frame()
        w.fw._scene_image = None
    finally:
        canvas.cull_offscreen = saved
    return screen(w)


def max_diff(a, b):
    return int(np.abs(a.astype(int) - b.astype(int)).max())


def painted_box(o):
    """Bounds of what ``o`` paints alone, in its own (world) coordinates."""
    eng = CV.ScenaCanvas.get_current()
    W, H, ox, oy = 1600, 1000, 800, 500
    surf = skia.Surface(W, H)
    saved = eng.skia_canvas
    eng.skia_canvas = surf.getCanvas()
    eng.skia_canvas.clear(skia.Color4f(0, 0, 0, 0))
    eng.skia_canvas.translate(ox, oy)
    try:
        eng._draw_object(o)
    finally:
        eng.skia_canvas = saved
    a = np.asarray(surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))
    ys, xs = np.nonzero(a[..., 3] > 0)
    return (xs.min() - ox, ys.min() - oy, xs.max() + 1 - ox, ys.max() + 1 - oy)


def covers(box, got, tol=1.0):
    return (box[0] <= got[0] + tol and box[1] <= got[1] + tol
            and box[2] >= got[2] - tol and box[3] >= got[3] - tol)


class TestCullBoxes(unittest.TestCase):
    """The box the cull tests covers what the body paints, cached or not."""

    def test_shield_scale_moves_the_cached_box(self):
        with system_world(draw=True) as w:
            with quiet():
                s = w.track(Sprite(TILE, size=40.0, center=(-200, 150)))
                s.visual = Shield()
            CV._cull_box(s)
            s.shield_scale = 12.0
            self.assertEqual(CV._cull_box(s), CV._cull_box_full(s))

    def test_a_contact_seated_sprite_is_not_shifted(self):
        # The seat puts the feet on the stored plane: a center move is not a
        # translation of the drawing.
        with system_world(draw=True) as w:
            with quiet():
                s = w.track(Sprite(TILE, size=64.0, center=(200, 150), hitbox_anchor="bottom"))
                s.tilt = TouchingContact(other=None, side="bottom", slope_angle=10.0,
                                         normal=Vec2(0.0, 1.0), tangent=Vec2(1.0, 0.0),
                                         point=(200.0, 100.0))
            for _ in range(3):
                CV._cull_box(s)
                s.move_by(0, 300)
                self.assertEqual(CV._cull_box(s), CV._cull_box_full(s))

    def test_a_bake_moves_a_tilted_box(self):
        # The tilt pivot reads the baked hull; the bake is lazy (enroll).
        with system_world(draw=True) as w:
            with quiet():
                s = w.track(Sprite(ninja_sheet("bottom"), center=(200, 150),
                                   hitbox_anchor="bottom"))
                s.tilt = 90.0
            CV._cull_box(s)
            CV._cull_box(s)
            s.collidable = True
            self.assertEqual(CV._cull_box(s), CV._cull_box_full(s))

    def test_extrude_is_never_culled(self):
        # Its slabs reach toward the vanishing point: no bound.
        with system_world(draw=True) as w:
            with quiet():
                o = w.track(Circle(center=(-5000, 150), radius=20))
                o.visual = Extrude()
            box = CV._cull_box(o)
            self.assertEqual(box, CV._INF_BOX4)

    def test_sprite_band_looks_and_cheap_glow_fit_their_box(self):
        def clip():
            sh = Sheet(anchor="bottom", pixel_size=0.5)
            sh.strip("mix", [os.path.join(SPACE, f) for f in
                             ("laserRed01.png", "ufoYellow.png", "star_gold.png")], fps=12)
            s = Sprite(sh, center=(0.0, 0.0))
            s.play("mix")
            return s

        with system_world(draw=False) as w:
            cases = []
            for look in ("halo", "rim", "cheap"):
                for make in (lambda: Sprite(TILE, size=40.0, center=(0.0, 0.0)), clip):
                    with quiet():
                        o = w.track(make())
                        if look == "halo":
                            o.visual = Halo()
                        elif look == "rim":
                            o.visual = Rim()
                        else:
                            o.glow = CheapGlow()
                    cases.append((look, o))
            for look, o in cases:
                for _ in range(3):
                    box = CV._cull_box_full(o)
                    got = painted_box(o)
                    self.assertTrue(covers(box, got), (look, box, got))
                    clock.advance(1.0 / 12.0)

    def test_verify_mode_raises_inside_a_frame(self):
        # The draw loop fails open on an exception; a stale box under verify
        # mode must not draw correctly and pass every pixel test.
        with system_world(draw=True) as w:
            with quiet():
                s = w.track(Sprite(TILE, size=40.0, center=(-200, 150)))
                s.visual = Shield()
                for i in range(3):
                    w.track(Sprite(TILE, size=10.0, center=(-900 - i, 150)))
            with mock.patch.object(C, "_POSE_REV_VERIFY", True), \
                    mock.patch.object(CV, "_CULL_BACKOFF", False):
                draw(w, True)
                object.__setattr__(s, "_shield_scale", 12.0)   # a writer with no bump
                with self.assertRaises(AssertionError):
                    draw(w, True)


class TestCullPlan(unittest.TestCase):
    """Culling never changes how the drawn objects batch (the plan keeps the
    culled objects in place), so the backoff never makes a still scene flicker."""

    def test_a_still_scene_draws_the_same_every_frame(self):
        with system_world(draw=True) as w:
            with quiet():
                for i in range(20):         # keeps the skip ratio under the backoff's
                    w.track(Circle(center=(15 + i * 19, 20), radius=4, color="white"))
                a = w.track(Rect(center=(200, 150), width=80, height=60, color="red"))
                a.fill_filter = Blur(6)
                w.track(Circle(center=(-400, 150), radius=10, color="green"))  # culled, between
                c = w.track(Rect(center=(230, 170), width=80, height=60, color="blue"))
                c.fill_filter = GlowFilter()
            for _ in range(8):              # cull on: tested frames and backoff frames
                w.step(1, draw=False)
                off = draw(w, False)        # the same frame drawn both ways (an
                on = draw(w, True)          # earlier module may leave a sky moving)
                self.assertEqual(max_diff(on, off), 0)

    def test_a_culled_member_keeps_a_segment_mixed(self):
        # A culled Blur shape starts a mixed segment with a kept DropShadow
        # one: without it the segment is one-key and reach pulls a later
        # DropShadow peer into it.
        from scena import DropShadow
        with system_world(draw=True) as w:
            with quiet():
                b = w.track(Circle(center=(-900, 150), radius=30, color="white"))
                b.fill_filter = Blur(6)
                p = w.track(Rect(center=(120, 150), width=60, height=60, color="tomato"))
                p.fill_filter = DropShadow()
                w.track(Rect(center=(-900, -900), width=5, height=5, color="cyan"))
                q = w.track(Rect(center=(150, 170), width=60, height=60, color="gold"))
                q.fill_filter = DropShadow()
            with mock.patch.object(CV, "_CULL_BACKOFF", False):
                self.assertEqual(max_diff(draw(w, True), draw(w, False)), 0)

    def test_a_look_run_left_with_one_drawn_stays_pass_major(self):
        # A run's pass-major emit and a solo render differ in edge AA (LP1):
        # the drawn peer of a culled one draws as the run does.
        from scena import Laser
        with system_world(draw=True) as w:
            with quiet():
                for x, y in ((200.3, 150.2), (-900.0, 150.0)):
                    o = w.track(Circle(center=(x, y), radius=3.8, color="cyan"))
                    o.visual = Laser()
            with mock.patch.object(CV, "_CULL_BACKOFF", False):
                self.assertEqual(max_diff(draw(w, True), draw(w, False)), 0)


if __name__ == "__main__":
    unittest.main()
