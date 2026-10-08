"""Framework inspect shortcuts: debug zoom, overlay pack, time cycle.

Headless (no GLFW window) — call helpers directly on ScenaFramework.

    python -m unittest tests.test_framework_debug -v
"""
import os
import sys
import time
import math
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import canvas, clock, init
from scena.canvas import ScenaCanvas
from scena.collision import get_collision_system
from scena.color import Color
from scena.orchestration import DEFAULT_SHOW_SYSTEM_INFO, ScenaFramework


class FrameworkDebugTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        canvas.cull_offscreen = False
        self.fw = ScenaFramework.get_instance()
        # Reset inspect state between tests (singleton) to product defaults.
        self.fw._overlay_pack = False
        self.fw._hud_before_overlay_pack = DEFAULT_SHOW_SYSTEM_INFO
        self.fw._show_system_info = DEFAULT_SHOW_SYSTEM_INFO
        self.fw._set_debug_zoom(1.0)
        self.fw._debug_time_step = 0
        self.fw._debug_time_saved_scale = 1.0
        clock.scale = 1.0
        clock.paused = False
        cs = get_collision_system()
        if cs is not None:
            cs.show_colliders(False)

    def tearDown(self):
        self.fw._set_debug_zoom(1.0)
        canvas.reset_view()
        self.fw._overlay_pack = False
        self.fw._debug_time_step = 0
        clock.scale = 1.0
        clock.paused = False
        cs = get_collision_system()
        if cs is not None:
            cs.show_colliders(False)


class TestDebugZoomCycle(FrameworkDebugTestCase):
    def test_cycle_sets_flag_and_returns_inactive(self):
        fw = self.fw
        eng = ScenaCanvas.get_current()
        self.assertFalse(fw._debug_zoom_active)
        self.assertFalse(eng._debug_zoom_active)
        self.assertEqual(fw._debug_zoom, 1.0)

        fw._cycle_debug_zoom()
        self.assertTrue(fw._debug_zoom_active)
        self.assertTrue(eng._debug_zoom_active)
        self.assertAlmostEqual(fw._debug_zoom, 0.5)

        fw._cycle_debug_zoom()
        self.assertTrue(fw._debug_zoom_active)
        self.assertAlmostEqual(fw._debug_zoom, 0.25)

        fw._cycle_debug_zoom()
        self.assertFalse(fw._debug_zoom_active)
        self.assertFalse(eng._debug_zoom_active)
        self.assertAlmostEqual(fw._debug_zoom, 1.0)

    def test_set_debug_zoom_one_clears_flag(self):
        fw = self.fw
        fw._set_debug_zoom(0.5)
        self.assertTrue(fw._debug_zoom_active)
        fw._set_debug_zoom(1.0)
        self.assertFalse(fw._debug_zoom_active)
        self.assertFalse(ScenaCanvas.get_current()._debug_zoom_active)


class TestOverlayPack(FrameworkDebugTestCase):
    def test_pack_saves_restores_hud_and_colliders(self):
        fw = self.fw
        cs = get_collision_system()
        self.assertIsNotNone(cs)
        self.assertIs(fw.collision_system, cs)

        fw._show_system_info = False
        fw._toggle_overlay_pack()
        self.assertTrue(fw._overlay_pack)
        self.assertTrue(fw._show_system_info)
        self.assertFalse(fw._hud_before_overlay_pack)
        self.assertTrue(bool(getattr(cs, "_show", False)))

        fw._toggle_overlay_pack()
        self.assertFalse(fw._overlay_pack)
        self.assertFalse(fw._show_system_info)  # restored
        self.assertFalse(bool(getattr(cs, "_show", False)))

    def test_draw_overlays_returns_immediately_when_off(self):
        fw = self.fw
        self.assertFalse(fw._overlay_pack)
        self.assertFalse(fw._debug_zoom_active)
        cs = get_collision_system()
        self.assertFalse(bool(getattr(cs, "_show", False)))
        fw._draw_debug_overlays(None)  # must not touch the canvas

    def test_pack_preserves_hud_on_when_was_on(self):
        fw = self.fw
        fw._show_system_info = True
        fw._toggle_overlay_pack()
        self.assertTrue(fw._show_system_info)
        fw._toggle_overlay_pack()
        self.assertTrue(fw._show_system_info)

    def test_bounds_stroke_only_when_enrolled(self):
        from scena.bounds import get_bounds_system, reset_bounds_system
        from scena import leave_playfield

        reset_bounds_system()
        sys = get_bounds_system()
        self.assertFalse(sys.enrolled)

        @leave_playfield("probe")
        def _probe(_item):
            pass

        self.assertTrue(sys.enrolled)
        sys.debug_stroke(None)


class TestDebugTimeCycle(FrameworkDebugTestCase):
    def test_pause_quarter_restores_author_scale(self):
        fw = self.fw
        clock.scale = 0.8
        self.assertAlmostEqual(clock.scale, 0.8)

        fw._cycle_debug_time()
        self.assertEqual(fw._debug_time_step, 1)
        self.assertTrue(clock.paused)
        self.assertAlmostEqual(clock.scale, 0.0)
        self.assertAlmostEqual(fw._debug_time_saved_scale, 0.8)

        fw._cycle_debug_time()
        self.assertEqual(fw._debug_time_step, 2)
        self.assertAlmostEqual(clock.scale, 0.25)
        self.assertFalse(clock.paused)

        fw._cycle_debug_time()
        self.assertEqual(fw._debug_time_step, 0)
        self.assertAlmostEqual(clock.scale, 0.8)
        self.assertFalse(clock.paused)

    def test_system_info_includes_inspect_suffixes(self):
        fw = self.fw
        fw._set_debug_zoom(0.5)
        fw._debug_time_step = 1
        text = fw._system_info_text()
        self.assertIn("xy:", text)
        self.assertIn("zoom:50%", text)
        self.assertIn("time:pause", text)
        self.assertEqual(text.split("  ")[-1], "time:pause", text)


class TestSystemHudRefresh(FrameworkDebugTestCase):
    def test_system_info_default_off(self):
        self.assertFalse(DEFAULT_SHOW_SYSTEM_INFO)
        self.assertFalse(self.fw._show_system_info)

    def test_stats_line_throttled_to_interval(self):
        class _DummyLabel:
            def __init__(self):
                self.text = ""
                self.visible = False

        fw = self.fw
        label = _DummyLabel()
        # The framework is a process singleton: put the real label back, or
        # the stub leaks into every later module in the same process.
        self.addCleanup(setattr, fw, "_system_label", fw._system_label)
        fw._system_label = label
        fw._show_system_info = True
        fw._feedback_until = 0.0
        fw._last_hud_info_time = None
        fw._refresh_system_label()
        self.assertTrue(label.text.startswith("FPS:"))
        self.assertIn("xy:", label.text)

        label.text = "stale"
        fw._last_hud_info_time = time.perf_counter()
        fw._refresh_system_label()
        self.assertEqual(label.text, "stale")

        fw._last_hud_info_time = time.perf_counter() - fw._HUD_INFO_INTERVAL_S
        fw._refresh_system_label()
        self.assertNotEqual(label.text, "stale")
        self.assertTrue(label.text.startswith("FPS:"))
        self.assertIn("xy:", label.text)


class TestDebugZoomHitFeedback(FrameworkDebugTestCase):
    def test_burst_uv_and_radius_follow_inspector(self):
        """Post overlays map world (x,y) through inspector scale; zoom-off unchanged.

        Camera is identity here — camera mapping is ``TestCameraHitFeedback``.
        """
        canvas.effects.clear()
        fw = self.fw
        W, H = float(fw.design_width), float(fw.design_height)
        x, y = W * 0.9, H * 0.85
        radius = 40.0

        canvas.burst_at(x, y, radius=radius)
        hit = canvas.effects._hit_feedback()
        uv_off = hit._bursts[0]["uv"]
        r_off = hit._bursts[0]["radius_design"]
        self.assertAlmostEqual(uv_off[0], x / W)
        self.assertAlmostEqual(uv_off[1], 1.0 - y / H)
        self.assertAlmostEqual(r_off, radius)

        canvas.effects.clear()
        fw._set_debug_zoom(0.5)
        canvas.burst_at(x, y, radius=radius)
        hit = canvas.effects._hit_feedback()
        uv_on = hit._bursts[0]["uv"]
        z = 0.5
        vx = W * 0.5 + z * (x - W * 0.5)
        vy = H * 0.5 + z * (y - H * 0.5)
        self.assertAlmostEqual(uv_on[0], vx / W)
        self.assertAlmostEqual(uv_on[1], 1.0 - vy / H)
        self.assertAlmostEqual(hit._bursts[0]["radius_design"], radius * z)

        canvas.effects.clear()
        fw._set_debug_zoom(1.0)
        canvas.burst_at(x, y, radius=radius)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._bursts[0]["uv"][0], uv_off[0])
        self.assertAlmostEqual(hit._bursts[0]["uv"][1], uv_off[1])
        self.assertAlmostEqual(hit._bursts[0]["radius_design"], r_off)

    def test_fireworks_uv_and_radius_follow_inspector(self):
        canvas.effects.clear()
        fw = self.fw
        W, H = float(fw.design_width), float(fw.design_height)
        x, y = W * 0.9, H * 0.85
        radius = 64.0

        canvas.fireworks_at(x, y, radius=radius, fall=0.55)
        hit = canvas.effects._hit_feedback()
        uv_off = hit._fireworks[0]["uv"]
        r_off = hit._fireworks[0]["radius_design"]
        self.assertAlmostEqual(uv_off[0], x / W)
        self.assertAlmostEqual(uv_off[1], 1.0 - y / H)
        self.assertAlmostEqual(r_off, radius)

        canvas.effects.clear()
        fw._set_debug_zoom(0.5)
        canvas.fireworks_at(x, y, radius=radius, fall=0.55)
        hit = canvas.effects._hit_feedback()
        z = 0.5
        vx = W * 0.5 + z * (x - W * 0.5)
        vy = H * 0.5 + z * (y - H * 0.5)
        self.assertAlmostEqual(hit._fireworks[0]["uv"][0], vx / W)
        self.assertAlmostEqual(hit._fireworks[0]["uv"][1], 1.0 - vy / H)
        self.assertAlmostEqual(hit._fireworks[0]["radius_design"], radius * z)

        canvas.effects.clear()
        fw._set_debug_zoom(1.0)
        canvas.fireworks_at(x, y, radius=radius, fall=0.55)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._fireworks[0]["uv"][0], uv_off[0])
        self.assertAlmostEqual(hit._fireworks[0]["uv"][1], uv_off[1])
        self.assertAlmostEqual(hit._fireworks[0]["radius_design"], r_off)

    def test_ripple_uv_follows_inspector(self):
        canvas.effects.clear()
        fw = self.fw
        W, H = float(fw.design_width), float(fw.design_height)
        x, y = 80.0, 120.0
        canvas.ripple_at(x, y, amount=0.5, radius=50.0, shock=True, shake=False)
        hit = canvas.effects._hit_feedback()
        uv_off = hit._ripple_uv
        r_off = hit._ripple_radius_design

        canvas.effects.clear()
        fw._set_debug_zoom(0.25)
        canvas.ripple_at(x, y, amount=0.5, radius=50.0, shock=True, shake=False)
        hit = canvas.effects._hit_feedback()
        z = 0.25
        vx = W * 0.5 + z * (x - W * 0.5)
        vy = H * 0.5 + z * (y - H * 0.5)
        self.assertAlmostEqual(hit._ripple_uv[0], vx / W)
        self.assertAlmostEqual(hit._ripple_uv[1], 1.0 - vy / H)
        self.assertAlmostEqual(hit._ripple_radius_design, r_off * z)

        fw._set_debug_zoom(1.0)
        self.assertAlmostEqual(uv_off[0], x / W)


class TestCameraHitFeedback(FrameworkDebugTestCase):
    """canvas.*_at overlays map world (x,y) through camera then debug zoom."""

    def _uv(self, x, y):
        fw = self.fw
        W, H = float(fw.design_width), float(fw.design_height)
        vx, vy = fw.world_to_view_coords(x, y)
        return vx / W, 1.0 - vy / H

    def test_burst_follows_pan(self):
        canvas.effects.clear()
        W, H = float(self.fw.design_width), float(self.fw.design_height)
        look = (300.0, 250.0)
        canvas.pan_to(*look)
        canvas.burst_at(*look, radius=40.0)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._bursts[0]["uv"][0], 0.5)
        self.assertAlmostEqual(hit._bursts[0]["uv"][1], 0.5)
        self.assertAlmostEqual(hit._bursts[0]["radius_design"], 40.0)

        canvas.effects.clear()
        x, y = look[0] + 80.0, look[1]
        canvas.burst_at(x, y, radius=40.0)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._bursts[0]["uv"][0], 0.5 + 80.0 / W)
        self.assertAlmostEqual(hit._bursts[0]["uv"][1], 0.5)

    def test_burst_follows_zoom(self):
        canvas.effects.clear()
        W, H = float(self.fw.design_width), float(self.fw.design_height)
        look = (W * 0.5, H * 0.5)
        canvas.zoom_to(2.0)
        canvas.burst_at(look[0], look[1], radius=40.0)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._bursts[0]["uv"][0], 0.5)
        self.assertAlmostEqual(hit._bursts[0]["uv"][1], 0.5)
        self.assertAlmostEqual(hit._bursts[0]["radius_design"], 80.0)

        canvas.effects.clear()
        x = look[0] + 50.0
        canvas.burst_at(x, look[1], radius=40.0)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._bursts[0]["uv"][0], 0.5 + 100.0 / W)
        self.assertAlmostEqual(hit._bursts[0]["uv"][1], 0.5)

    def test_burst_follows_rotate(self):
        canvas.effects.clear()
        canvas.rotate_to(90.0)
        # Y-up +90° CCW: world (500, 500) with look at center (500, 400)
        # delta (0, +100) → (-100, 0) → view (400, 400)
        canvas.burst_at(500.0, 500.0, radius=24.0)
        hit = canvas.effects._hit_feedback()
        W, H = float(self.fw.design_width), float(self.fw.design_height)
        self.assertAlmostEqual(hit._bursts[0]["uv"][0], 400.0 / W)
        self.assertAlmostEqual(hit._bursts[0]["uv"][1], 1.0 - 400.0 / H)

    def test_burst_camera_then_debug_zoom(self):
        canvas.effects.clear()
        fw = self.fw
        W, H = float(fw.design_width), float(fw.design_height)
        look = (300.0, 250.0)
        world = (look[0] + 80.0, look[1] + 40.0)
        radius = 40.0
        canvas.zoom_to(2.0).pan_to(*look).rotate_to(15.0)
        fw._set_debug_zoom(0.5)
        canvas.burst_at(*world, radius=radius)
        hit = canvas.effects._hit_feedback()
        eu, ev = self._uv(*world)
        self.assertAlmostEqual(hit._bursts[0]["uv"][0], eu)
        self.assertAlmostEqual(hit._bursts[0]["uv"][1], ev)
        self.assertAlmostEqual(
            hit._bursts[0]["radius_design"],
            radius * fw.world_to_view_scale(),
        )
        self.assertAlmostEqual(fw.world_to_view_scale(), 1.0)

        canvas.effects.clear()
        canvas.reset_view()
        fw._set_debug_zoom(1.0)
        canvas.burst_at(*world, radius=radius)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._bursts[0]["uv"][0], world[0] / W)
        self.assertAlmostEqual(hit._bursts[0]["uv"][1], 1.0 - world[1] / H)
        self.assertAlmostEqual(hit._bursts[0]["radius_design"], radius)

    def test_fireworks_and_ripple_follow_camera(self):
        canvas.effects.clear()
        look = (300.0, 250.0)
        canvas.zoom_to(2.0).pan_to(*look)
        canvas.fireworks_at(*look, radius=64.0, fall=0.55)
        canvas.ripple_at(look[0] + 20.0, look[1], amount=0.5, radius=50.0,
                         shock=True, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._fireworks[0]["uv"][0], 0.5)
        self.assertAlmostEqual(hit._fireworks[0]["uv"][1], 0.5)
        self.assertAlmostEqual(hit._fireworks[0]["radius_design"], 128.0)
        eu, ev = self._uv(look[0] + 20.0, look[1])
        self.assertAlmostEqual(hit._ripple_uv[0], eu)
        self.assertAlmostEqual(hit._ripple_uv[1], ev)
        self.assertAlmostEqual(hit._ripple_radius_design, 100.0)

    def test_wave_angle_follows_camera_rotation(self):
        canvas.effects.clear()
        canvas.wave_at(500.0, 400.0, angle=0.0, shock=False, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._ripple_angle, 0.0)

        canvas.effects.clear()
        canvas.rotate_to(90.0)
        canvas.wave_at(500.0, 400.0, angle=0.0, shock=False, shake=False)
        hit = canvas.effects._hit_feedback()
        # World +X after +90° CCW is +Y; FB y-down flips that to -pi/2.
        self.assertAlmostEqual(hit._ripple_angle, -math.pi / 2.0)

    def test_fireworks_uv_tracks_live_camera(self):
        """Follow-cam: overlay stays on the world point after pan (not baked UV)."""
        canvas.effects.clear()
        world = (300.0, 250.0)
        canvas.zoom_to(3.0).pan_to(*world)
        canvas.fireworks_at(*world, radius=64.0, fall=0.0)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._fireworks[0]["uv"][0], 0.5)
        self.assertAlmostEqual(hit._fireworks[0]["uv"][1], 0.5)

        # Camera drops (landing follow): baked UV would sit below the hero.
        canvas.pan_to(300.0, 180.0)
        hit.tick_frame(0.0, canvas)
        eu, ev = self._uv(*world)
        self.assertAlmostEqual(hit._fireworks[0]["uv"][0], eu)
        self.assertAlmostEqual(hit._fireworks[0]["uv"][1], ev)
        self.assertNotAlmostEqual(hit._fireworks[0]["uv"][1], 0.5, places=3)
        self.assertAlmostEqual(
            hit._fireworks[0]["radius_design"],
            64.0 * self.fw.world_to_view_scale(),
        )


class AuthorErrorBannerTest(FrameworkDebugTestCase):
    def test_last_author_error_payload_for_hud(self):
        """The banner carries SCENA WARNINGs only; author errors raise."""
        import scena
        from scena.process import (
            clear_author_error,
            last_author_error,
            report_author_warning,
        )
        import warnings

        self.assertFalse(hasattr(scena, "report_author_error"))
        clear_author_error()
        self.assertIsNone(last_author_error())
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            report_author_warning("play_sound", "missing.wav not found")
        err = last_author_error()
        self.assertIsNotNone(err)
        self.assertEqual(err["where"], "play_sound")
        self.assertEqual(err["severity"], "warning")
        self.assertIn("missing.wav", err["message"])
        self.assertEqual(err["count"], 1)

        clear_author_error()
        self.assertIsNone(last_author_error())
        self.fw._error_label = None
        self.fw._refresh_error_label()  # no-op without label

    def test_warning_hud_pair_is_opaque_light_on_dark(self):
        fg = Color(*ScenaFramework._WARN_HUD_FG)
        bg = Color(*ScenaFramework._WARN_HUD_BG)
        self.assertAlmostEqual(bg.alpha, 1.0)
        self.assertGreater(fg.brightness, 0.8)
        self.assertLess(bg.brightness, 0.35)
        self.assertFalse(hasattr(ScenaFramework, "_ERROR_HUD_FG"))  # no error plate


if __name__ == "__main__":
    unittest.main()
