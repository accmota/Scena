"""``speed=`` on the timed pose verbs: the rate instead of the duration.

``move_to`` / ``move_by`` / ``move_along`` / ``rotate_to`` / ``rotate_by`` and
the camera's ``pan_to`` / ``pan_by`` take ``speed=`` (units, or degrees, per
second) in place of ``time=``. The duration is the distance ÷ speed, read once
at the call; from there the job is the same tween ``time=`` builds, so
``ease=`` / ``loops=`` / ``yoyo=`` / ``then=`` / pause / ``time_scale`` work
unchanged. ``time=`` and ``speed=`` together raise, and so does a bad rate.

Bug class guarded by ``TestEveryTimedVerbIsClassified``: a timed verb that
forgets ``speed=`` (or takes it where a rate has no meaning). Every public
method with ``time=`` must be in ``SPEED_VERBS`` (and take ``speed=``) or in
``NO_SPEED`` (and refuse it).

    python tests/run_tiers.py focused test_timed_speed
"""
from __future__ import annotations

import inspect
import math
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase, quiet  # noqa: E402

import scena  # noqa: E402
from scena import (  # noqa: E402
    Circle, Handle, Rect, Sprite, Track, canvas, group, tween,
)

from tests.leftovers import module_sweep  # noqa: E402
from tests.test_sprite import _write_rect_png  # noqa: E402

setUpModule, tearDownModule = module_sweep()

BAD_SPEEDS = (0, -1, -0.5, float("nan"), float("inf"), 10 ** 400, True, "fast", [1], lambda: 3)


class SpeedCase(SystemTestCase, unittest.TestCase):
    world_draw = False

    def setUp(self):
        super().setUp()
        warnings.simplefilter("ignore", RuntimeWarning)

    def circle(self, x=0.0, y=0.0):
        return self.track(Circle(center=(x, y), radius=5))


class TestDurationFromDistance(SpeedCase):
    def test_move_to_duration_is_distance_over_speed_and_lands(self):
        c = self.circle()
        h = c.move_to(300, 400, speed=100)
        self.assertIsInstance(h, Handle)
        self.assertAlmostEqual(h.delay, 5.0)
        self.w.seconds(5.2)
        self.assertTrue(h.done)
        self.assertAlmostEqual(c.center.x, 300.0, places=6)
        self.assertAlmostEqual(c.center.y, 400.0, places=6)

    def test_move_to_one_axis_counts_only_that_axis(self):
        c = self.circle(7, 0)
        h = c.move_to(None, 50, speed=10)
        self.assertAlmostEqual(h.delay, 5.0)

    def test_move_to_about_measures_from_the_pivot(self):
        r = self.track(Rect(center=(0, 0), width=20, height=10))
        # The pivot (-10, -5) travels to (100, -5): 110 units.
        h = r.move_to(100, -5, about=(-10, -5), speed=11)
        self.assertAlmostEqual(h.delay, 10.0)

    def test_move_to_point_like_target_is_frozen(self):
        c = self.circle()
        goal = self.circle(30, 40)
        h = c.move_to(goal, speed=10)
        self.assertAlmostEqual(h.delay, 5.0)
        goal.move_to(500, 500)
        self.w.seconds(5.2)
        self.assertAlmostEqual(c.center.x, 30.0, places=6)

    def test_move_by_cartesian_and_polar(self):
        c = self.circle()
        self.assertAlmostEqual(c.move_by(30, 40, speed=10).delay, 5.0)
        self.assertAlmostEqual(c.move_by(angle=90, distance=50, speed=25).delay, 2.0)
        self.assertAlmostEqual(c.move_by(-60, 80, speed=50).delay, 2.0)

    def test_rotate_to_takes_the_short_arc(self):
        r = self.track(Rect(center=(0, 0), width=20, height=10, angle=350))
        h = r.rotate_to(10, speed=20)          # 20° the short way
        self.assertAlmostEqual(h.delay, 1.0)
        self.w.seconds(1.2)
        self.assertAlmostEqual(r.angle % 360.0, 10.0, places=6)

    def test_rotate_by_uses_the_size_of_the_turn(self):
        r = self.track(Rect(center=(0, 0), width=20, height=10))
        h = r.rotate_by(-90, speed=45)
        self.assertAlmostEqual(h.delay, 2.0)
        self.w.seconds(2.2)
        self.assertAlmostEqual(r.angle, -90.0, places=6)

    def test_reset_rotation_turns_back_at_the_rate(self):
        r = self.track(Rect(center=(0, 0), width=20, height=10, angle=90))
        h = r.reset_rotation(speed=45)
        self.assertAlmostEqual(h.delay, 2.0)
        self.w.seconds(2.2)
        self.assertAlmostEqual(r.angle % 360.0, 0.0, places=6)

    def test_rotate_by_about_is_degrees_per_second_of_the_turn(self):
        r = self.track(Rect(center=(0, 0), width=20, height=10))
        h = r.rotate_by(180, about=(100, 0), speed=90)
        self.assertAlmostEqual(h.delay, 2.0)

    def test_move_along_is_length_times_window(self):
        t = self.track(Track.circle(radius=100))
        L = float(t.length)
        c = self.circle()
        self.assertAlmostEqual(c.move_along(t, speed=L / 4).delay, 4.0)
        self.assertAlmostEqual(c.move_along(t, speed=L / 4, span=(0.25, 0.75)).delay, 2.0)
        self.assertAlmostEqual(c.move_along(t, speed=L / 4, span=(1, 0)).delay, 4.0)
        self.assertAlmostEqual(c.move_along(t, speed=L / 4, phase=0.3).delay, 4.0)

    def test_move_along_reads_the_scaled_length(self):
        t = self.track(Track.circle(radius=100))
        L = float(t.length)
        t.scale_to(2)
        c = self.circle()
        self.assertAlmostEqual(float(t.length), 2 * L, places=6)
        self.assertAlmostEqual(c.move_along(t, speed=L).delay, 2.0)

    def test_move_along_a_shape_outline_and_a_reversed_view(self):
        sq = self.track(Rect(center=(0, 0), width=100, height=100))
        c = self.circle()
        self.assertAlmostEqual(c.move_along(sq, speed=100).delay, 4.0)
        t = self.track(Track.circle(radius=100))
        L = float(t.length)
        self.assertAlmostEqual(c.move_along(t.reversed(), speed=L).delay, 1.0)

    def test_move_along_freezes_the_lap_at_the_call(self):
        t = self.track(Track.circle(radius=100))
        L = float(t.length)
        c = self.circle()
        h = c.move_along(t, speed=L / 2)
        t.scale_to(3)
        self.assertAlmostEqual(h.delay, 2.0)


class TestSameTweenAfterwards(SpeedCase):
    def test_linear_readout_reads_the_requested_speed(self):
        c = self.circle()
        h = c.move_to(300, 400, speed=100)
        self.w.step(3)
        self.assertAlmostEqual(h.speed, 100.0, places=3)

    def test_ride_readout_reads_the_requested_speed(self):
        t = self.track(Track.circle(radius=100))
        c = self.circle()
        h = c.move_along(t, speed=120)
        self.w.step(5)
        self.assertAlmostEqual(h.speed, 120.0, delta=120 * 0.08)

    def test_ease_makes_it_the_average_speed(self):
        c = self.circle()
        h = c.move_to(100, 0, speed=50, ease="ease_in_out")
        self.assertAlmostEqual(h.delay, 2.0)
        self.w.seconds(2.2)
        self.assertAlmostEqual(c.center.x, 100.0, places=6)

    def test_loops_and_yoyo_count_per_leg(self):
        c = self.circle()
        h = c.move_by(100, 0, speed=100, loops=3)
        self.assertAlmostEqual(h.remaining, 3.0)
        c2 = self.circle()
        h2 = c2.move_by(100, 0, speed=50, loops=2, yoyo=True)
        self.assertAlmostEqual(h2.remaining, 4.0)

    def test_then_and_on_done_fire(self):
        c = self.circle()
        seen = []
        c.move_to(10, 0, speed=100, on_done=lambda: seen.append("done"))
        self.w.seconds(0.2)
        self.assertEqual(seen, ["done"])

    def test_zero_distance_finishes_on_the_next_tick(self):
        c = self.circle(5, 5)
        seen = []
        h = c.move_to(5, 5, speed=50, on_done=lambda: seen.append(1))
        self.assertEqual(h.delay, 0.0)
        self.w.step(1)
        self.assertTrue(h.done)
        self.assertEqual(seen, [1])
        h2 = c.move_by(0, 0, speed=50, loops="forever")
        self.w.step(3)
        self.assertTrue(h2.done, "a zero-length forever loop must not spin")

    def test_time_scale_stretches_wall_time(self):
        c = self.circle()
        c.time_scale = 0.5
        c.move_to(100, 0, speed=50)
        self.w.seconds(2.0)
        self.assertAlmostEqual(c.center.x, 50.0, delta=2.0)

    def test_pause_holds(self):
        c = self.circle()
        h = c.move_to(100, 0, speed=50)
        self.w.seconds(0.5)
        x = c.center.x
        h.pause()
        self.w.seconds(0.5)
        self.assertAlmostEqual(c.center.x, x, places=9)

    def test_conflict_label_names_speed(self):
        c = self.circle()
        h = c.move_to(100, 0, speed=50)
        self.assertEqual(h._claim_label, "move_to(speed=50)")

    def test_every_kind_takes_speed(self):
        from surface_support import make_instance
        for name in ("Circle", "Rect", "Line", "Polygon", "Ellipse", "Point", "Text"):
            with self.subTest(kind=name):
                with quiet():
                    obj = self.track(make_instance(name))
                x0, y0 = float(obj.center.x), float(obj.center.y)
                h = obj.move_to(x0 + 30, y0 + 40, speed=10)
                self.assertAlmostEqual(h.delay, 5.0)
                h.cancel()
                h = obj.rotate_by(90, speed=45)
                self.assertAlmostEqual(h.delay, 2.0)
                h.cancel()

    def test_sprite_takes_speed(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="scena_speed_")
        path = os.path.join(d, "r.png")
        _write_rect_png(path, 16, 8)
        s = self.track(Sprite(path, center=(0, 0)))
        self.assertAlmostEqual(s.move_to(30, 40, speed=5).delay, 10.0)
        self.assertAlmostEqual(s.rotate_to(45, speed=45).delay, 1.0)

    def test_group_members_each_get_their_own_duration(self):
        a = self.circle(0, 0).tag("speedgrp")
        b = self.circle(-100, 0).tag("speedgrp")
        group["speedgrp"].move_to(100, 0, speed=100)
        self.w.seconds(1.05)
        self.assertAlmostEqual(a.center.x, 100.0, places=6)
        self.assertLess(b.center.x, 100.0)
        self.w.seconds(1.05)
        self.assertAlmostEqual(b.center.x, 100.0, places=6)

    def test_empty_group_is_a_finished_timer(self):
        h = group["speedgrp_none"].move_to(10, 10, speed=5)
        self.assertIsInstance(h, Handle)
        self.w.step(1)
        self.assertTrue(h.done)
        with self.assertRaises(ValueError):
            group["speedgrp_none"].move_to(10, 10, speed=0)


class TestCamera(SpeedCase):
    def tearDown(self):
        canvas.reset_view()
        super().tearDown()

    def test_pan_to_and_pan_by(self):
        canvas.pan_to(0, 0)
        h = canvas.pan_to(300, 400, speed=100)
        self.assertAlmostEqual(h.delay, 5.0)
        h.cancel()
        h = canvas.pan_by(30, 40, speed=10)
        self.assertAlmostEqual(h.delay, 5.0)

    def test_pan_lands(self):
        canvas.pan_to(0, 0)
        canvas.pan_to(60, 80, speed=200)
        self.w.seconds(0.6)
        eng = canvas._engine
        self.assertAlmostEqual(eng._look_x, 60.0, places=6)
        self.assertAlmostEqual(eng._look_y, 80.0, places=6)

    def test_other_camera_verbs_refuse_speed(self):
        for call in (lambda: canvas.zoom_to(2, speed=1), lambda: canvas.zoom_by(2, speed=1),
                     lambda: canvas.rotate_to(30, speed=10), lambda: canvas.rotate_by(30, speed=10),
                     lambda: canvas.reset_view(speed=1)):
            with self.assertRaises(TypeError):
                call()


def _verbs(c):
    """Every speed verb on one fresh circle (and the camera), as calls of ``**kw``."""
    t = Track.circle(radius=50)
    return {
        "move_to": lambda **kw: c.move_to(100, 0, **kw),
        "move_by": lambda **kw: c.move_by(100, 0, **kw),
        "move_along": lambda **kw: c.move_along(t, **kw),
        "rotate_to": lambda **kw: c.rotate_to(90, **kw),
        "rotate_by": lambda **kw: c.rotate_by(90, **kw),
        "pan_to": lambda **kw: canvas.pan_to(100, 0, **kw),
        "pan_by": lambda **kw: canvas.pan_by(100, 0, **kw),
    }


class TestRefusals(SpeedCase):
    def tearDown(self):
        canvas.reset_view()
        super().tearDown()

    def test_a_bad_speed_raises_and_names_it(self):
        c = self.circle()
        for name, call in _verbs(c).items():
            for bad in BAD_SPEEDS:
                with self.subTest(verb=name, speed=bad):
                    with self.assertRaises((TypeError, ValueError)) as cm:
                        call(speed=bad)
                    self.assertIn("speed=", str(cm.exception))

    def test_time_and_speed_together_raise(self):
        c = self.circle()
        for name, call in _verbs(c).items():
            with self.subTest(verb=name):
                with self.assertRaises(TypeError) as cm:
                    call(time=1, speed=10)
                self.assertIn("time= and speed=", str(cm.exception))

    def test_a_refused_speed_keeps_the_job_in_flight(self):
        c = self.circle()
        for name, call in _verbs(c).items():
            with self.subTest(verb=name):
                h = call(time=1)
                self.w.step(2)
                with self.assertRaises((TypeError, ValueError)):
                    call(speed=0)
                with self.assertRaises(TypeError):
                    call(time=1, speed=5)
                self.assertFalse(h.cancelled, f"a refused {name}(speed=) cancelled the job")
                h.cancel()

    def test_move_along_needs_time_or_speed(self):
        c = self.circle()
        with self.assertRaises(TypeError) as cm:
            c.move_along(Track.circle(radius=10))
        self.assertIn("time=", str(cm.exception))
        self.assertIn("speed=", str(cm.exception))

    def test_scale_and_tween_refuse_speed(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="scena_speed_")
        path = os.path.join(d, "r.png")
        _write_rect_png(path, 16, 8)
        r = self.track(Rect(center=(0, 0), width=20, height=10))
        c = self.circle()
        s = self.track(Sprite(path, center=(0, 0)))
        for obj in (r, c, s):
            for verb in ("scale_to", "scale_by"):
                with self.subTest(kind=type(obj).__name__, verb=verb):
                    with self.assertRaises(TypeError):
                        getattr(obj, verb)(2, speed=1)
                    with self.assertRaises(TypeError):
                        getattr(obj, verb)(2, time=1, speed=1)
        with self.assertRaises(TypeError):
            tween(r["width"], 50, speed=10)

    def test_timing_messages_name_speed_only_where_it_exists(self):
        c = self.circle()
        with self.assertRaises(TypeError) as cm:
            c.move_to(10, 0, ease="in_out")
        self.assertIn("time= or speed=", str(cm.exception))
        with self.assertRaises(TypeError) as cm:
            c.rotate_by(10, loops=2)
        self.assertIn("time= or speed=", str(cm.exception))
        with self.assertRaises(TypeError) as cm:
            c.scale_to(2, ease="in_out")
        self.assertNotIn("speed", str(cm.exception))
        with self.assertRaises(TypeError) as cm:
            canvas.zoom_to(2, loops=2)
        self.assertNotIn("speed", str(cm.exception))


# Every public timed verb is one or the other.
SPEED_VERBS = {"move_to", "move_by", "move_along", "rotate_to", "rotate_by", "reset_rotation"}
CAMERA_SPEED_VERBS = {"pan_to", "pan_by"}
NO_SPEED = {
    "scale_to": "a scale is a ratio: there is no distance to cover at a rate",
    "scale_by": "a scale is a ratio: there is no distance to cover at a rate",
    "zoom_to": "a zoom is a ratio",
    "zoom_by": "a zoom is a ratio",
    "frame_to": "pan, zoom and turn at once: no one rate",
    "set_origin": "a reset of the look-at, not a trip",
    "reset_view": "pan, zoom and turn at once: no one rate",
    "camera.rotate_to": "kept to time= (decided with pan only)",
    "camera.rotate_by": "kept to time= (decided with pan only)",
}


class TestEveryTimedVerbIsClassified(SpeedCase):
    def test_walk(self):
        from test_value_validation import _ARGS, _method_instances, _POINT_FIRST
        from test_hyp_surface import _ARG_BY_NAME
        guesses = {**_ARG_BY_NAME, **_ARGS, "value": 1.0, "factor": 1.1, "target": "circle"}
        subjects = list(_method_instances()) + [("canvas", lambda: scena.canvas)]
        problems, seen = {}, set()
        for label, factory in subjects:
            with quiet():
                inst = factory()
            cls = type(inst)
            for attr in sorted(dir(cls)):
                if attr.startswith("_") or not callable(inspect.getattr_static(cls, attr, None)):
                    continue
                with quiet():
                    method = getattr(inst, attr)
                try:
                    params = inspect.signature(method).parameters
                except (TypeError, ValueError):
                    continue
                timed = "time" in params or getattr(method, "_timed_wrapped", False)
                if not timed:
                    continue
                key = f"camera.{attr}" if label == "canvas" else attr
                speed_verb = (attr in CAMERA_SPEED_VERBS) if label == "canvas" else (attr in SPEED_VERBS)
                if not speed_verb and key not in NO_SPEED and attr not in NO_SPEED and attr != "tween":
                    problems[f"{label}.{attr}"] = "timed verb not classified: add speed= or list it in NO_SPEED"
                    continue
                if attr in _POINT_FIRST:
                    args = [(1.0, 1.0)]
                elif attr in ("move_to", "move_by"):
                    args = [10.0, 10.0]
                else:
                    need = [p for p in params.values() if p.default is p.empty
                            and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                            and p.kind is not p.KEYWORD_ONLY]
                    if any(p.name not in guesses for p in need):
                        problems[f"{label}.{attr}"] = "no argument guess (add one)"
                        continue
                    args = [guesses[p.name] for p in need]
                seen.add(f"{label}.{attr}")
                try:
                    with quiet():
                        out = getattr(factory(), attr)(*args, speed=5)
                except TypeError as e:
                    if speed_verb:
                        problems[f"{label}.{attr}"] = f"refused speed=: {str(e)[:70]}"
                    continue
                except Exception as e:  # noqa: BLE001
                    problems[f"{label}.{attr}"] = f"{type(e).__name__}: {str(e)[:70]}"
                    continue
                if not speed_verb:
                    problems[f"{label}.{attr}"] = "took speed= but is listed in NO_SPEED"
                elif not isinstance(out, Handle):
                    problems[f"{label}.{attr}"] = f"speed= returned {type(out).__name__}, not a Handle"
                elif isinstance(out, Handle):
                    out.cancel()
        self.maxDiff = None
        self.assertGreater(len(seen), 40, "vacuous walk")
        self.assertEqual(problems, {})


if __name__ == "__main__":
    unittest.main()
