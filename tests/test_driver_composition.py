"""
Persistent driver composition (Shapes Design — Persistent drivers vs linked pose).

Only a formula (``@=``) is exclusive. Every other persistent driver —
pointer drag, ``wheel_rotate``, motion Handles (``tween`` / timed pose verbs /
``move_along``), standing ``resolve()`` — composes, in either declaration
order. A pointer hold *holds* the motion on the parts it writes (a private
gate, not ``Handle.pause()``). Conflict messages name the actor by the line
that made it, the driver in place, and every resolve pair.

Bug class pinned here: a driver pair whose outcome depends on which line ran
first (the old one-way ``_PROCESS_CLAIM_REFUSING_OPS`` refusal).

Run headless:

    python -m pytest tests/test_driver_composition.py -q
"""

from __future__ import annotations

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import clock, group, tween
from scena.canvas import ScenaCanvas
from scena.collision import (
    STATIC, get_collision_system, reset_collision_system, resolve, unresolve,
)
from scena.entity import entity_label
from scena.input import Mouse
from scena.orchestration import ShapeInteractionManager
from scena.process import (
    process_claims_on, reset_process_scheduler, tick_processes,
)
from scena.shapes import Circle, Line, Rect
from scena.state import LinkedAttributeError
from scena.track import Track


def _frame(dt=0.1):
    clock.advance(dt)
    tick_processes()


class DriverCase(unittest.TestCase):
    _origin = 0

    def setUp(self):
        reset_process_scheduler()
        reset_collision_system()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        self._owned = []
        DriverCase._origin += 3000
        self.origin = DriverCase._origin
        self.sim = ShapeInteractionManager(ScenaCanvas.get_current().registry)
        self.btn = Mouse.BTN_LEFT
        self.sim.drag_threshold = 5.0

    def tearDown(self):
        for s in self._owned:
            try:
                if s.is_alive:
                    s.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_collision_system()
        reset_process_scheduler()

    def track(self, obj):
        self._owned.append(obj)
        return obj

    def at(self, x, y):
        return (self.origin + x, self.origin + y)


# ---------------------------------------------------------------------------
# Bug class: order independence over every driver pair
# ---------------------------------------------------------------------------

# name -> (part written, declare(shape, src))
def _formula_center(r, src):
    r.center @= src.center


def _formula_rotation(r, src):
    r["angle"] @= src["angle"]


def _drag(r, src):
    r.draggable = True


def _wheel(r, src):
    r.wheel_rotate = True


def _tween_center(r, src):
    tween(r.center, (r.center.x + 50, r.center.y), time=1.0)


def _tween_rotation(r, src):
    tween(r["angle"], 90, time=1.0)


def _move_by(r, src):
    r.move_by(100, 0, time=1.0)


def _rotate_by(r, src):
    r.rotate_by(90, time=1.0)


def _move_along(r, src):
    r.move_along("eight", time=1.0)


def _resolve(r, src):
    resolve("drv_body", "drv_wall")


DRIVERS = {
    "formula_center": ("center", _formula_center),
    "formula_rotation": ("angle", _formula_rotation),
    "draggable": ("center", _drag),
    "wheel_rotate": ("angle", _wheel),
    "tween_center": ("center", _tween_center),
    "tween_rotation": ("angle", _tween_rotation),
    "move_by_time": ("center", _move_by),
    "rotate_by_time": ("angle", _rotate_by),
    "move_along": ("center", _move_along),
    "resolve": ("center", _resolve),
}


class TestOrderIndependence(DriverCase):
    def _run(self, a, b):
        reset_process_scheduler()
        reset_collision_system()
        ox, oy = self.at(0, 0)
        src = self.track(Rect(center=(ox + 5, oy + 5), width=2, height=2))
        self.track(Rect(center=(ox + 300, oy), width=20, height=200, group="drv_wall"))
        r = self.track(Rect(center=(ox, oy), width=20, height=20, group="drv_body"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                DRIVERS[a][1](r, src)
                DRIVERS[b][1](r, src)
            except LinkedAttributeError:
                return "raise"
            finally:
                # A linked leftover in "drv_body" would refuse the next resolve().
                for s in list(self._owned):
                    s.destroy()
                self._owned.clear()
        return "ok"

    def test_every_pair_same_outcome_both_orders_only_formula_raises(self):
        names = list(DRIVERS)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if a.startswith("formula") and b.startswith("formula"):
                    continue
                with self.subTest(a=a, b=b):
                    ab = self._run(a, b)
                    ba = self._run(b, a)
                    self.assertEqual(ab, ba, f"{a}/{b} depends on order: {ab} vs {ba}")
                    has_formula = a.startswith("formula") or b.startswith("formula")
                    same_part = DRIVERS[a][0] == DRIVERS[b][0]
                    want = "raise" if (has_formula and same_part) else "ok"
                    self.assertEqual(ab, want, f"{a}/{b}")

    def test_same_kind_replace_still_warns(self):
        ox, oy = self.at(0, 0)
        r = self.track(Rect(center=(ox, oy), width=20, height=20))
        h1 = tween(r.center, (ox + 50, oy), time=1.0)
        with self.assertWarns(RuntimeWarning):
            h2 = tween(r.center, (ox + 80, oy), time=1.0)
        self.assertTrue(h1.cancelled)
        self.assertFalse(h2.cancelled)


class TestCloneMotionThenResolve(DriverCase):
    def _run(self, *, resolve_first: bool) -> float:
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(center=(ox + 200, oy), width=20, height=120, group="walls"))
        wall.mass = STATIC
        heroi = self.track(Rect(center=(ox - 500, oy), width=20, height=20, group="heroi"))
        if resolve_first:
            resolve("heroi", "walls")
        h = self.track(heroi.clone())  # joins "heroi" (clone copies groups)
        h.move_to(ox, oy)
        # Forever laps replay the segment; stay inside the first lap (1.5 s of 2 s).
        h.move_by(400, 0, loops="forever", time=2.0)
        if not resolve_first:
            resolve("heroi", "walls")  # used to raise: the clone's motion claimed center
        dt = 1.0 / 60.0
        for _ in range(90):
            clock.advance(dt)
            tick_processes()
            get_collision_system().step()
        return float(h.center.x) - ox

    def test_clone_forever_move_then_resolve_stops_at_wall_either_order(self):
        motion_first = self._run(resolve_first=False)
        self.setUp()
        resolve_first = self._run(resolve_first=True)
        # Wall face at +190, half-width 10: the clone rests just short of +180.
        for x in (motion_first, resolve_first):
            self.assertLess(x, 181.0)
            self.assertGreater(x, 170.0)


# ---------------------------------------------------------------------------
# Pointer hold
# ---------------------------------------------------------------------------

class TestPointerHold(DriverCase):
    def _patrol(self, *, loops="forever"):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=20))
        c.draggable = True
        h = c.move_by(100, 0, time=1.0, loops=loops)
        return c, h, ox, oy

    def _grab(self, c, dx=10.0):
        x, y = float(c.center.x), float(c.center.y)
        self.assertTrue(self.sim.handle_mouse_down(x, y, self.btn))
        self.assertTrue(self.sim.handle_mouse_move(x + dx, y))
        return x + dx, y

    def test_hold_freezes_motion_without_touching_paused(self):
        c, h, ox, oy = self._patrol()
        px, py = self._grab(c)
        self.assertTrue(h._held)
        self.assertFalse(h.paused)
        elapsed = h.elapsed
        _frame(0.5)
        self.assertEqual(h.elapsed, elapsed)
        self.assertAlmostEqual(float(c.center.x), px, places=4)
        self.sim.handle_mouse_up(px, py, self.btn)
        self.assertFalse(h._held)
        _frame(0.5)
        # Push motion continues from the drop point.
        self.assertAlmostEqual(float(c.center.x), px + 50.0, places=3)

    def test_author_pause_is_theirs_across_the_hold(self):
        c, h, ox, oy = self._patrol()
        h.pause()
        px, py = self._grab(c)
        self.sim.handle_mouse_up(px, py, self.btn)
        self.assertTrue(h.paused)
        _frame(0.5)
        self.assertAlmostEqual(float(c.center.x), px, places=4)

    def test_author_resume_during_hold_waits_for_release(self):
        c, h, ox, oy = self._patrol()
        h.pause()
        px, py = self._grab(c)
        h.resume()
        _frame(0.5)
        self.assertAlmostEqual(float(c.center.x), px, places=4)
        self.sim.handle_mouse_up(px, py, self.btn)
        _frame(0.5)
        self.assertAlmostEqual(float(c.center.x), px + 50.0, places=3)

    def test_author_pause_during_hold_survives_release(self):
        c, h, ox, oy = self._patrol()
        px, py = self._grab(c)
        h.pause()
        self.sim.handle_mouse_up(px, py, self.btn)
        self.assertTrue(h.paused)
        _frame(0.5)
        self.assertAlmostEqual(float(c.center.x), px, places=4)

    def test_grab_offset_restarts_at_threshold(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=20))
        c.draggable = True
        c.move_by(1000, 0, time=10.0)
        self.assertTrue(self.sim.handle_mouse_down(ox, oy, self.btn))
        _frame(0.5)  # 50 DU of motion before the threshold is crossed
        self.assertAlmostEqual(float(c.center.x), ox + 50.0, places=3)
        self.sim.handle_mouse_move(ox + 6, oy)
        # Only the pointer's travel (+6), no jump back to the press position.
        self.assertAlmostEqual(float(c.center.x), ox + 56.0, places=3)

    def test_draggable_false_mid_hold_ends_hold_now(self):
        c, h, ox, oy = self._patrol()
        drops = []
        c.on_drag_to = lambda s, t, pos: drops.append(pos)
        px, py = self._grab(c)
        c.draggable = False
        self.assertFalse(h._held)  # before any pointer event
        _frame(0.5)
        self.assertAlmostEqual(float(c.center.x), px + 50.0, places=3)
        self.sim.handle_mouse_move(px + 200, py)
        self.assertAlmostEqual(float(c.center.x), px + 50.0, places=3)
        self.sim.handle_mouse_up(px + 200, py, self.btn)
        self.assertEqual(drops, [])

    def test_destroy_mid_hold_leaves_nothing_held(self):
        c, h, ox, oy = self._patrol()
        px, py = self._grab(c)
        c.destroy()
        self.sim.handle_mouse_move(px + 20, py)  # used to raise DestroyedError
        self.sim.handle_mouse_up(px + 20, py, self.btn)
        self.assertIsNone(self.sim._pressed_shape)
        self.assertFalse(h._held)
        _frame(0.1)
        self.assertTrue(h.cancelled)

    def test_motion_started_during_hold_is_held(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=20))
        c.draggable = True
        started = []

        def over(s, t, pos):
            if not started:
                started.append(s.move_by(100, 0, time=1.0))

        c.on_drag_over = over
        px, py = self._grab(c)
        self.assertEqual(len(started), 1)
        h = started[0]
        self.assertTrue(h._held)
        _frame(0.5)
        self.assertAlmostEqual(float(c.center.x), px, places=4)
        self.sim.handle_mouse_up(px, py, self.btn)
        _frame(0.5)
        self.assertAlmostEqual(float(c.center.x), px + 50.0, places=3)

    def test_wheel_tick_holds_rotation_tween(self):
        ox, oy = self.at(0, 0)
        r = self.track(Rect(center=(ox, oy), width=40, height=20))
        r.wheel_rotate = True
        r.draggable = True  # a press needs a pressable shape
        h = tween(r["angle"], 90, time=1.0)
        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.assertFalse(h._held)  # a press alone does not write rotation
        self.sim.handle_mouse_scroll(ox, oy, 0, 1)
        self.assertTrue(h._held)
        after_wheel = float(r.angle)
        _frame(0.3)
        self.assertAlmostEqual(float(r.angle), after_wheel, places=4)
        self.sim.handle_mouse_up(ox, oy, self.btn)
        self.assertFalse(h._held)

    def test_one_handle_on_two_held_parts_is_held_once(self):
        ox, oy = self.at(0, 0)
        line = self.track(Line(p1=(ox, oy), p2=(ox + 100, oy)))
        line.draggable = True
        h = line.move_by(100, 0, time=1.0)
        self.assertEqual(
            [x for p in line._parts_written_by_drag() for x in process_claims_on(p)],
            [h, h],
        )
        self.sim.handle_mouse_down(ox + 50, oy, self.btn)
        self.sim.handle_mouse_move(ox + 60, oy)
        self.assertEqual(line.__dict__["_hold_handles"], [h])
        self.sim.handle_mouse_up(ox + 60, oy, self.btn)
        self.assertNotIn("_hold_handles", line.__dict__)

    def test_snap_back_in_on_drag_to_arrives(self):
        ox, oy = self.at(0, 0)
        card = self.track(Circle(center=(ox, oy), radius=20))
        card.draggable = True
        card.on_drag_to = lambda s, t, pos: s.move_to(ox, oy, time=0.3)
        self._grab(card, dx=80)
        self.sim.handle_mouse_up(ox + 80, oy, self.btn)
        self.assertTrue(card.draggable)
        for _ in range(4):
            _frame(0.1)
        self.assertAlmostEqual(float(card.center.x), ox, places=3)


# ---------------------------------------------------------------------------
# Messages: name the actor, both drivers, every pair
# ---------------------------------------------------------------------------

class TestConflictMessages(DriverCase):
    def test_formula_clone_in_resolved_group_names_clone_line_and_group(self):
        ox, oy = self.at(0, 0)
        src = self.track(Circle(center=(ox, oy), radius=1))
        heroi = self.track(Rect(center=(ox, oy), width=10, height=10, group="heroi"))
        heroi_line = heroi.__dict__["_site"][1]
        h = self.track(heroi.clone()); clone_line = sys._getframe().f_lineno
        h.center @= src.center
        self.track(Rect(center=(ox, oy - 50), width=100, height=10, group="plataforma"))
        with self.assertRaises(LinkedAttributeError) as ctx:
            resolve(["heroi"], ["plataforma"])
        msg = str(ctx.exception)
        self.assertIn(f"made at test_driver_composition.py:{clone_line}", msg)
        self.assertIn(f"a clone of the one from line {heroi_line}", msg)
        self.assertIn('group "heroi"', msg)
        self.assertIn("clone(group=None)", msg)
        self.assertNotIn(f"made at test_driver_composition.py:{heroi_line}", msg)

    def test_resolve_list_side_is_all_or_nothing(self):
        ox, oy = self.at(0, 0)
        src = self.track(Circle(center=(ox, oy), radius=1))
        self.track(Rect(center=(ox + 50, oy), width=10, height=10, group="tchau"))
        linked = self.track(Rect(center=(ox, oy), width=10, height=10, group="heroi"))
        linked.center @= src.center
        self.track(Rect(center=(ox, oy - 50), width=100, height=10, group="plataforma"))
        with self.assertRaises(LinkedAttributeError):
            resolve(["tchau", "heroi"], "plataforma")
        self.assertEqual(get_collision_system()._resolve_pairs, [])

    def test_link_after_resolve_names_every_pair(self):
        ox, oy = self.at(0, 0)
        src = self.track(Circle(center=(ox, oy), radius=1))
        body = self.track(Rect(center=(ox, oy), width=10, height=10, group="heroi"))
        self.track(Rect(center=(ox, oy - 50), width=100, height=10, group="plataforma"))
        self.track(Rect(center=(ox + 80, oy), width=10, height=100, group="parede"))
        resolve(["heroi", "tchau"], ["plataforma", "parede"])
        with self.assertRaises(LinkedAttributeError) as ctx:
            body.center @= src.center
        msg = str(ctx.exception)
        self.assertIn('resolve("heroi", ["plataforma", "parede"]) nudges it', msg)
        self.assertIn('unresolve("heroi", ["plataforma", "parede"])', msg)
        unresolve("heroi", ["plataforma", "parede"])
        body.center @= src.center  # the hint was complete

    def test_forever_motion_drops_wait_hint(self):
        ox, oy = self.at(0, 0)
        src = self.track(Circle(center=(ox, oy), radius=1))
        r = self.track(Rect(center=(ox, oy), width=10, height=10))
        h = r.move_by(10, 0, time=2, loops="forever")
        with self.assertRaises(LinkedAttributeError) as ctx:
            r.center @= src.center
        msg = str(ctx.exception)
        self.assertIn('move_by(time=2, loops="forever") pushes it', msg)
        self.assertNotIn("wait", msg)
        h.cancel()
        h = r.move_by(10, 0, time=2)
        with self.assertRaises(LinkedAttributeError) as ctx:
            r.center @= src.center
        self.assertIn("or wait for the motion to finish", str(ctx.exception))

    def test_placement_tween_reads_sets(self):
        ox, oy = self.at(0, 0)
        r = self.track(Rect(center=(ox, oy), width=10, height=10))
        tween(r["angle"], 90, time=1.5)
        with self.assertRaises(LinkedAttributeError) as ctx:
            r["angle"] @= (lambda: 5)
        self.assertIn("tween(time=1.5) sets it", str(ctx.exception))

    def test_label_is_the_construction_line(self):
        # There are no author ids: a message names the actor by its line.
        ox, oy = self.at(0, 0)
        r = self.track(Rect(center=(ox, oy), width=10, height=10))
        label = entity_label(r)
        self.assertRegex(label, r"^the Rect made at test_driver_composition\.py:\d+$")
        self.assertEqual(entity_label(r.center), label)


class TestSiteCapture(DriverCase):
    def test_parts_have_no_site_actor_has_author_line(self):
        ox, oy = self.at(0, 0)
        r = self.track(Rect(center=(ox, oy), width=10, height=10)); line = sys._getframe().f_lineno
        self.assertEqual(r.__dict__["_site"], (__file__, line))
        self.assertIn(f"made at test_driver_composition.py:{line}", entity_label(r.center))

    def test_helper_in_author_file_records_helper_line(self):
        ox, oy = self.at(0, 0)

        def spawn():
            return Rect(center=(ox, oy), width=5, height=5)  # site
        r = self.track(spawn())
        site_line = spawn.__code__.co_firstlineno + 1
        self.assertEqual(r.__dict__["_site"][1], site_line)


# ---------------------------------------------------------------------------
# Carry: a move_along in flight plus a per-frame move_by add up
# ---------------------------------------------------------------------------

class TestCarry(DriverCase):
    """The "carry" line of a camera-moves game: things that ride the screen get
    ``group[...].move_by(dx, 0)`` every frame while their own ``move_along``
    runs. The ride must shift by exactly the summed carry, every frame — never
    be overwritten by the travel driver, never be applied twice. Proof is a twin
    rider on the same path without carry: ``carried − twin == carry so far``.
    """

    DX, DY = 12.0, -3.0

    def _pair(self, path_for, suffix=""):
        ox, oy = self.at(0, 0)
        tag = f"tela_{self.origin}{suffix}"
        a = self.track(Circle(center=(ox, oy), radius=4, group=tag))
        b = self.track(Circle(center=(ox, oy), radius=4))
        ha = a.move_along(path_for(ox, oy), time=1.0)
        hb = b.move_along(path_for(ox, oy), time=1.0)
        return a, b, ha, hb, tag

    def _assert_offset(self, a, b, n):
        self.assertAlmostEqual(float(a.center.x) - float(b.center.x), self.DX * n, places=4)
        self.assertAlmostEqual(float(a.center.y) - float(b.center.y), self.DY * n, places=4)

    def _run(self, path_for, *, carry_first=True, frames=14, suffix=""):
        a, b, ha, hb, tag = self._pair(path_for, suffix)
        for n in range(1, frames + 1):
            clock.advance(0.1)
            if carry_first:                      # frame order: update(dt) before the process tick
                group[tag].move_by(self.DX, self.DY)
                tick_processes()
            else:
                tick_processes()
                group[tag].move_by(self.DX, self.DY)
            self._assert_offset(a, b, n)
        # Past the end (frames > 10): the ride is done, carry still moves it.
        self.assertTrue(ha.done and hb.done)
        return a, b

    @staticmethod
    def _floating(ox, oy):
        return Track(points=[(0, 0), (100, 0), (100, 100)], smooth=0, floating=True)

    @staticmethod
    def _anchored(ox, oy):
        return Track(points=[(ox + 40, oy), (ox + 140, oy + 60), (ox + 40, oy + 120)])

    def test_floating_track_plus_carry_adds_every_frame(self):
        a, b = self._run(self._floating)
        # The twin ends at the path's far end, relative to where it started.
        ox, oy = self.at(0, 0)
        self.assertAlmostEqual(float(b.center.x), ox + 100, places=3)
        self.assertAlmostEqual(float(b.center.y), oy + 100, places=3)

    def test_anchored_track_plus_carry_adds_every_frame(self):
        self._run(self._anchored)

    def test_carry_order_in_frame_does_not_matter(self):
        # Both pairs start at self.at(0, 0); separate groups so one carry moves one pair.
        a1, _ = self._run(self._floating, carry_first=True, suffix="_a")
        a2, _ = self._run(self._floating, carry_first=False, suffix="_b")
        self.assertAlmostEqual(float(a1.center.x), float(a2.center.x), places=4)
        self.assertAlmostEqual(float(a1.center.y), float(a2.center.y), places=4)

    def test_preset_floating_loop_plus_carry(self):
        # Formation idiom: a forever loop that stays on screen while the camera moves.
        ox, oy = self.at(0, 0)
        tag = f"tela_{self.origin}"
        a = self.track(Circle(center=(ox, oy), radius=4, group=tag))
        b = self.track(Circle(center=(ox, oy), radius=4))
        a.move_along("eight", time=1.0, loops="forever")
        b.move_along("eight", time=1.0, loops="forever")
        for n in range(1, 26):
            clock.advance(0.1)
            group[tag].move_by(self.DX, self.DY)
            tick_processes()
            self._assert_offset(a, b, n)


if __name__ == "__main__":
    unittest.main()
