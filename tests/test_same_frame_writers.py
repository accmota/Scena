"""A writer later in the frame is seen by the readers after it (review 2026-10-09, writers × time).

Bug class: **a reader that runs before a writer in the same frame, or trusts a
cache the writer did not invalidate**. A handler's respawn was invisible to
that step's resolve; a query in ``update()`` used a linked hitbox switch from
the step before; the cull and ``.box`` measured a stale linked pose; a
Portal's tilt was outside its cache key; a timed zoom was linear; ``center =``
after ``move_by`` kept the sweep; the pointer was sampled before the camera
moved.

    python tests/run_tiers.py focused test_same_frame_writers
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import system_world  # noqa: E402

from scena import (  # noqa: E402
    STATIC, Circle, Portal, Rect, Sprite, State, canvas, collide, collision,
    group, resolve,
)

from tests.input_driver import input_driver  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402
from tests.test_sprite import _write_rect_png  # noqa: E402

setUpModule, tearDownModule = module_sweep()
FRAME = 1 / 60


class TestHandlerWritesReachResolve(unittest.TestCase):
    """W-G1: a respawn in a hazard handler lands on the spawn point."""

    def _respawn(self, how):
        spawn = (0.0, 200.0)
        with system_world(draw=False) as w:
            hero = Circle(center=(20, 0), radius=10, group="sf_hero")
            Rect(center=(65, 0), width=20, height=100, group="sf_wall").mass = STATIC
            Rect(center=(60, 0), width=6, height=100, group="sf_spike")
            resolve("sf_hero", "sf_wall")
            fired = []

            @collide("sf_hero", "sf_spike")
            def hit(h, s):
                fired.append(1)
                if how == "move_to":
                    h.move_to(spawn)
                else:
                    h.center = spawn

            w.on_update(lambda dt: None if fired else hero.move_by(10, 0))
            w.step(6)
            return fired, (hero.center.x, hero.center.y)

    def test_respawn(self):
        for how in ("move_to", "center"):
            with self.subTest(how=how):
                fired, pos = self._respawn(how)
                self.assertTrue(fired, "not vacuous")
                self.assertAlmostEqual(pos[0], 0.0, places=6)
                self.assertAlmostEqual(pos[1], 200.0, places=6)


class TestQueriesPollLinkedHitboxes(unittest.TestCase):
    """W-G2: a query in ``update()`` sees a linked ``active`` turned off."""

    def test_every_door(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        png = os.path.join(tmp, "box.png")
        _write_rect_png(png, 32, 32)
        for which in ("part", "main"):
            for declared in (False, True):
                with self.subTest(which=which, declared=declared), system_world(draw=False) as w:
                    st = State()
                    st.on = True
                    s = Sprite(png, center=(0, 0), size=32, group="sf_body")
                    if which == "part":
                        hb = s.add_hitbox(group="sf_atk", shape="rect")
                        hb["active"] @= (lambda: st.on)
                        tag = "sf_atk"
                    else:
                        s.hitbox["active"] @= (lambda: st.on)
                        tag = "sf_body"
                    Circle(center=(5000, 5000), radius=1, group="sf_probe")
                    if declared:
                        @collide(tag, "sf_probe")
                        def h(a, b):
                            pass
                    w.step(2)
                    seen = {}

                    def upd(dt):
                        if seen:
                            return
                        st.on = False
                        seen["named"] = s in collision.query_point(0, 0, group=tag)
                        seen["anything"] = s in collision.query_point(0, 0)

                    w.on_update(upd)
                    w.step(1)
                    self.assertFalse(seen["named"])
                    if which == "main":
                        self.assertFalse(seen["anything"])


class TestMeasuringReadersPull(unittest.TestCase):
    """W-G3 / X-writers-5: the cull and ``.box`` pull a linked pose."""

    def test_group_box_and_box_see_the_link(self):
        with system_world(draw=False) as w:
            st = State()
            st.k = 1.0
            r = Rect(center=(0, 0), width=20, height=10, group="sf_g")
            r["scale"] @= (lambda: st.k)
            w.step(1)
            st.k = 5.0
            self.assertAlmostEqual(group["sf_g"].box.width, 100.0)
            self.assertAlmostEqual(r.box.width, 100.0)

    def test_cull_keeps_a_shape_linked_into_view(self):
        with system_world(draw=True) as w:
            st = State()
            st.k = 1.0
            # Off view at scale 1, its right edge reaches the view at scale 10.
            r = Rect(center=(-60, 150), width=20, height=20)
            r["scale"] @= (lambda: st.k)
            canvas.cull_offscreen = True
            try:
                w.step(1)
                st.k = 10.0
                eng = w.fw._scena_draw
                layer = eng.registry.layers["default"]
                self.assertTrue(eng._passes_cull(r, layer=layer))
            finally:
                canvas.cull_offscreen = False


class TestPortalKey(unittest.TestCase):
    """W-G4: ``tilt`` / ``angle`` are in Portal's collision key."""

    def test_tilt_rebuilds_the_hull(self):
        with system_world(draw=False) as w:
            portal = Portal(center=(0, 0), radius=60, group="sf_portal")
            w.step(1)
            self.assertIn(portal, collision.query_point(0, 50, group="sf_portal"))
            portal.tilt = 80
            self.assertNotIn(portal, collision.query_point(0, 50, group="sf_portal"))


class TestTimedZoomIsGeometric(unittest.TestCase):
    """X-writers-3: Canvas Design's geometric zoom channel."""

    def test_half_time_and_overshoot(self):
        with system_world(draw=False) as w:
            canvas.reset_view()
            canvas.zoom_to(4, time=1)
            w.seconds(0.5)
            self.assertAlmostEqual(canvas.zoom, 2.0, places=3)
            w.seconds(1)
            canvas.reset_view()
            low = [1.0]
            canvas.zoom_to(0.2, time=1, ease="elastic")
            for _ in range(70):
                w.step(1)
                low[0] = min(low[0], canvas.zoom)
            self.assertGreater(low[0], 0.1)
            canvas.reset_view()


class TestPlacementEndsTheSweep(unittest.TestCase):
    """X-writers-4: ``center =`` / ``center.x =`` / ``center <<`` are placement."""

    def test_respawn_after_a_move_is_not_swept(self):
        for how in ("center", "xy", "lshift"):
            with self.subTest(how=how), system_world(draw=False) as w:
                hero = Circle(center=(-200, 0), radius=5, group="sf_h")
                Rect(center=(-100, 0), width=4, height=100, group="sf_w")
                hits = []

                @collide("sf_h", "sf_w")
                def h(a, b):
                    hits.append(1)
                w.step(1)

                def upd(dt):
                    hero.move_by(300, 0)            # past the wall ...
                    if how == "center":             # ... then a respawn at x=0
                        hero.center = (0, 0)
                    elif how == "xy":
                        hero.center.x = 0
                        hero.center.y = 0
                    else:
                        hero.center << (0, 0)
                    w.on_update(None)
                w.on_update(upd)
                w.step(2)
                self.assertEqual(hits, [], "a respawn swept through a wall it never crossed")


class TestPointerFollowsTheCamera(unittest.TestCase):
    """W-P1: a camera moved in ``update`` resamples the world pointer."""

    def test_drag_and_mouse_link_stay_under_a_still_cursor(self):
        from scena import mouse
        with system_world(draw=False) as w, input_driver(w) as d:
            fw = w.fw
            cx, cy = fw.design_width / 2, fw.design_height / 2
            canvas.pan_to(1000, 600)
            unit = Circle(center=(1000, 600), radius=30)
            unit.draggable = True
            cross = Circle(center=(0, 0), radius=2)
            cross["center"] @= (lambda: mouse)
            w.step(1)
            d.move(cx, cy)
            w.step(1)
            d.down()
            d.move(cx + 10, cy)
            w.step(1)
            d.move(cx, cy)
            w.step(2)
            self.assertTrue(fw.shape_manager._dragging, "not vacuous")
            w.on_update(lambda dt: canvas.pan_by(300 * dt, 0))
            for _ in range(5):
                w.step(1)
                ux, _uy = fw.world_to_view_coords(unit.center.x, unit.center.y)
                kx, _ky = fw.world_to_view_coords(cross.center.x, cross.center.y)
                self.assertAlmostEqual(ux, cx, places=6)
                self.assertAlmostEqual(kx, cx, places=6)
            w.on_update(None)
            d.up()
            w.step(1)
            canvas.reset_view()


if __name__ == "__main__":
    unittest.main()
