"""Two doors to one answer give the same answer (review 2026-10-09, root cause R7).

Bug class: **one payload, several doors**. Each door had its own test, so
nothing compared them: the pointer hit test against the collision query,
``force=True`` against an unlinked twin, a ``reversed()`` view against its
host, one pivot under three verbs, Box against Rect, ``confine`` against the
public ``move_to``, ``"walls"`` against ``group["walls"]``. Each test below
is a differential: the same question through two doors.

    python tests/run_tiers.py focused test_doors_agree
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase, quiet  # noqa: E402

from scena import (  # noqa: E402
    Box, Circle, Point, Polygon, Rect, Sheet, Sprite, State, Text, Track, clock,
    collide, collision, group, ready, recently, resolve, unresolve, canvas,
)
from scena.collision import get_collision_system  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402
from tests.test_sprite import _write_rect_png  # noqa: E402

setUpModule, tearDownModule = module_sweep()


class TestHitTestPullsTheLinkedPose(SystemTestCase, unittest.TestCase):
    """S6-6: ``contains_point`` pulls a linked angle / scale, as draw and the
    collision query do; an undrawn shape answered with its old pose."""
    world_draw = True

    def test_hidden_shapes_answer_like_the_query(self):
        st = State()
        st.a, st.k = 0.0, 1.0
        q = self.w.track(Polygon(points=[(-100, -5), (100, -5), (100, 5), (-100, 5)],
                                 group="da_q"))
        q.visible = False
        q["angle"] @= (lambda: st.a)
        s = self.w.track(Polygon(points=[(-10, -10), (10, -10), (10, 10), (-10, 10)],
                                 group="da_s"))
        s.visible = False
        s["scale"] @= (lambda: st.k)
        self.w.step(2)
        st.a, st.k = 90.0, 5.0
        self.w.step(3)
        self.assertEqual(q.contains_point(0, 60),
                         q in collision.query_point(0, 60, group="da_q"))
        self.assertTrue(q.contains_point(0, 60))
        self.assertEqual(s.contains_point(40, 0),
                         s in collision.query_point(40, 0, group="da_s"))
        self.assertTrue(s.contains_point(40, 0))

    def test_text_in_the_same_frame_as_its_source_change(self):
        st = State()
        st.a = 0.0
        t = self.w.track(Text("a long caption here", center=(0, 0)))
        t["angle"] @= (lambda: st.a)
        self.w.step(2)
        y = 0.4 * (t._x2 - t._x1)
        st.a = 90.0                       # no frame between: the pull decides
        self.assertTrue(t.contains_point(0, y))


class TestForceUsesTheFreshPose(SystemTestCase, unittest.TestCase):
    """S6-1: a ``force=True`` verb on a linked pose computes from the value
    the link holds now, like an unlinked twin at that pose."""
    world_draw = False

    def test_scale_to_and_rotate_to_with_force(self):
        st = State()
        st.k, st.a = 1.0, 10.0
        rect = self.w.track(Rect(center=(0, 0), width=20, height=10))
        rect["scale"] @= (lambda: st.k)
        poly = self.w.track(Polygon(points=[(0, 0), (40, 0), (0, 20)]))
        poly["angle"] @= (lambda: st.a)
        self.w.step(2)
        st.k, st.a = 3.0, 50.0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rect.scale_to(2, force=True)
            poly.rotate_to(90, force=True)
        self.w.step(1)
        self.assertAlmostEqual(float(rect.width), 40.0)
        self.assertAlmostEqual(float(poly.angle), 90.0)


class TestReversedViewRidesLikeItsHost(SystemTestCase, unittest.TestCase):
    """S6-2: ``move_along(view)`` reads the host's pose and closure."""
    world_draw = False

    def test_floating_rotated_host(self):
        t = self.w.track(Track.line(length=200))
        t.rotate_to(90)
        r = self.w.track(Circle(center=(0, 0), radius=5))
        r.move_along(t.reversed(), time=1)
        self.assertEqual((round(r.center.x, 3), round(r.center.y, 3)), (0.0, 0.0))

    def test_a_host_that_became_closed_wraps(self):
        t2 = self.w.track(Track(points=[(0, 0), (100, 0)]))
        rv = t2.reversed()
        t2 << Track.circle(radius=50, center=(0, 0))
        r2 = self.w.track(Circle(center=(0, 0), radius=3))
        r2.move_along(rv, time=1, phase=0.5)
        self.w.step(50)
        a = (round(r2.center.x, 2), round(r2.center.y, 2))
        self.w.step(8)
        b = (round(r2.center.x, 2), round(r2.center.y, 2))
        self.assertNotEqual(a, b, "the ride parked as on an open path")


class TestOnePivotRule(SystemTestCase, unittest.TestCase):
    """S6-4 / S7-3: one rule says "this point is the pivot", for every verb
    and for Box as for Rect."""
    world_draw = False

    def test_a_pivot_a_rounding_off_a_linked_center(self):
        hub = self.w.track(Point(0.1, 0.7))
        r = self.w.track(Rect(center=lambda: hub + (0.2, 0.0), width=10, height=6))
        c = self.w.track(Circle(center=lambda: hub + (0.2, 0.0), radius=3))
        self.w.step(1)
        piv = (r.center.x + 1e-15, r.center.y)
        outcomes = {}
        for name, fn in (("Rect.rotate_by", lambda: r.rotate_by(30, about=piv)),
                         ("Rect.scale_by", lambda: r.scale_by(1.5, about=piv)),
                         ("Circle.rotate_by", lambda: c.rotate_by(30, about=piv))):
            try:
                fn()
                outcomes[name] = "ok"
            except Exception as exc:        # noqa: BLE001 — the outcome is the answer
                outcomes[name] = type(exc).__name__
        self.assertEqual(set(outcomes.values()), {"ok"}, outcomes)
        self.assertTrue(r["center"].is_linked and c["center"].is_linked)

    def test_box_and_rect_turn_about_a_linked_corner(self):
        results = {}
        for kind in (Rect, Box):
            anchor = self.w.track(Point(10, 20))
            shape = kind(p1=(10, 20), p2=(50, 40))
            if kind is Rect:
                self.w.track(shape)
            shape["p1"] @= anchor
            try:
                shape.rotate_by(30, about=(10, 20))
                results[kind.__name__] = ("ok", round(float(shape.angle), 6))
            except Exception as exc:        # noqa: BLE001
                results[kind.__name__] = (type(exc).__name__,)
        self.assertEqual(results["Box"], results["Rect"])
        self.assertEqual(results["Box"][0], "ok")

    def test_box_and_rect_turn_every_model_alike(self):
        cases = (
            dict(p1=(0, 0), p2=(40, 20)),
            dict(top_left=(0, 20), width=40, height=20),
            dict(center=(20, 10), width=40, height=20),
            dict(p1=(0, 0), vec=(40, 20)),
        )
        for kw in cases:
            with self.subTest(model=sorted(kw)):
                r = self.w.track(Rect(**kw))
                b = Box(**kw)
                for shape in (r, b):
                    shape.rotate_by(30, about=(5, 5))
                self.assertEqual(
                    [round(v, 9) for v in r._oriented_frame()],
                    [round(v, 9) for v in b._oriented_frame()])


class TestConfineSweepsLikeMoveTo(unittest.TestCase):
    """S7-4: a clamp by ``confine`` cuts the sweep where the body stopped,
    like a clamp by the public ``move_to``."""

    def _run(self, use_confine):
        from system_support import system_world
        hits = []
        with system_world(draw=False) as w:
            arena = Box(p1=(-400, -300), p2=(400, 300))
            shot = Circle(center=(390, 0), radius=2, group="da_shot")
            mine = Circle(center=(372, 0), radius=2, group="da_mine")

            @collide("da_shot", "da_mine")
            def hit(a, b, info):
                hits.append(clock.frame)
            w.step(1)

            def update(dt):
                if float(shot.center.x) < 399.5:
                    shot.move_by(30, 0)
                    if use_confine:
                        shot.confine(arena)
                    else:
                        shot.move_to(min(float(shot.center.x), 400), 0)
            w.on_update(update)
            w.step(3)
            x = float(shot.center.x)
            shot.destroy()
            mine.destroy()
        return x, hits

    def test_no_ghost_contact_behind_the_clamp(self):
        self.assertEqual(self._run(True), self._run(False))


class TestSideSpellingsAgree(SystemTestCase, unittest.TestCase):
    """S9-7: ``"t"`` and ``group["t"]`` are one side for ``unresolve``."""
    world_draw = False

    def test_unresolve_matches_every_spelling(self):
        cs = get_collision_system()
        hero = self.w.track(Rect(center=(0, 0), width=20, height=20))
        self.w.track(Rect(center=(15, 0), width=20, height=20, group="da_walls"))
        for made, undone in (('group["da_walls"]', 'group["da_walls"]'),
                             ('"da_walls"', 'group["da_walls"]'),
                             ('group["da_walls"]', '"da_walls"')):
            with self.subTest(resolve=made, unresolve=undone):
                resolve(hero, eval(made))
                self.assertEqual(len(cs._resolve_pairs), 1)
                unresolve(hero, eval(undone))
                self.assertEqual(cs._resolve_pairs, [])


class TestSmallRefusals(SystemTestCase, unittest.TestCase):
    """S9-9, S2-15: a value the setter cannot mean is refused, and a name is
    checked before the dict lookup."""
    world_draw = False

    def test_layer_visible_and_z(self):
        layer = canvas.layers.create("da_layer")
        self.addCleanup(lambda: "da_layer" in canvas.layers
                        and canvas.layers["da_layer"].delete())
        with self.assertRaises(TypeError):
            layer.visible = "no"
        self.assertTrue(layer.visible)
        layer.visible = 0
        self.assertIs(layer.visible, False)
        with self.assertRaises(ValueError):
            layer.z = 5.5
        layer.z = 6.0
        self.assertEqual(layer.z, 6)

    def test_poll_names_are_checked_first(self):
        for call in (ready.reset, ready.disable, ready.enable, ready.remove,
                     recently.reset, recently.remove):
            with self.subTest(call=call.__name__):
                with self.assertRaises(TypeError) as cm:
                    call(["fire"])
                self.assertNotIn("unhashable", str(cm.exception))

    def test_disable_before_the_first_poll(self):
        ready.disable("da_fire")
        self.assertFalse(ready("da_fire", 0.5))
        self.w.step(40)
        self.assertFalse(ready("da_fire"))
        ready.enable("da_fire")
        self.assertTrue(ready("da_fire"))
        self.assertFalse(ready("da_fire"))
        ready.remove("da_fire")


class TestMinHoldIsDueByReached(SystemTestCase, unittest.TestCase):
    """S7-2: ``play(min_hold=0.25)`` holds 15 frames at 1/60, whatever the
    start frame (a bare ``<`` held 16 for most)."""
    world_draw = False

    def test_hold_frames(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "s.png")
        _write_rect_png(path, 64, 16)
        sheet = Sheet(path, cols=4, fps=60)
        sheet.clip("run", [0, 1], fps=10)
        sheet.clip("idle", [2, 3], fps=10)
        held = {}
        for start in (2, 8, 20):
            hero = Sprite(sheet, frame=0, width=16, height=16, center=(0, 0))
            self.w.step(start)
            hero.play("run", min_hold=0.25)
            n = 0
            while True:
                self.w.step(1)
                n += 1
                hero.play("idle")
                if hero._play_name == "idle" or n > 40:
                    break
            held[start] = n
            hero.destroy()
        self.assertEqual(set(held.values()), {15}, held)



class TestPointerMapsInFloat64(SystemTestCase, unittest.TestCase):
    """S9-11: pointer -> world and world -> view are float64 closed forms;
    the float32 Skia inverse was 0.05 units off at x ~ 1e6. The draw matrix
    stays the reference for the convention (near the origin both agree)."""
    world_draw = False

    def test_round_trip_at_large_coordinates(self):
        fw = self.w.fw
        eng = fw._scena_draw
        for base in (1e3, 1e6, 1e7):
            for zoom, rot in ((1.0, 0.0), (2.0, 30.0), (0.5, -75.0)):
                with self.subTest(base=base, zoom=zoom, rot=rot):
                    look = (base + 0.37, base * 0.5 + 0.11)
                    eng.reset_view()
                    eng.pan_to(*look)
                    eng.zoom_to(zoom)
                    eng.rotate_to(rot)
                    wx, wy = look[0] + 13.3, look[1] - 7.1
                    vx, vy = fw.world_to_view_coords(wx, wy)
                    vs = fw.view_scale or 1.0
                    sx = fw._letterbox_pad_x + vx * vs
                    sy = fw._letterbox_pad_y + (fw.design_height - vy) * vs
                    bx, by = fw.screen_to_world_coords(sx, sy)
                    self.assertAlmostEqual(bx, wx, delta=1e-9 * max(1.0, base))
                    self.assertAlmostEqual(by, wy, delta=1e-9 * max(1.0, base))
        eng.reset_view()

    def test_same_convention_as_the_draw_matrix(self):
        fw = self.w.fw
        eng = fw._scena_draw
        eng.reset_view()
        eng.pan_to(40, -25)
        eng.zoom_to(1.7)
        eng.rotate_to(33)
        p = eng._camera_matrix.mapXY(12.5, 7.25)
        vx, vy = fw.world_to_view_coords(12.5, 7.25)
        self.assertAlmostEqual(vx, p.x(), places=3)
        self.assertAlmostEqual(vy, p.y(), places=3)
        eng.reset_view()


if __name__ == "__main__":
    unittest.main()
