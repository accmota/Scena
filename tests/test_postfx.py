"""
Post-FX engine and built-in effects tests (headless).

    python -m unittest tests.test_postfx -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    canvas, init,
    Circle, Point, Vec2,
    Vignette, Grain, Bloom, Grade, Chroma, Pixelate, Haze, Scanlines, ScreenBlur,
    Prism, Perspective, Lamp, GodRays, Spotlight, DistantLight,
    ColorSweep, ColorWash, CosmicBloom,
    Kaleidoscope, Wash, MotionTrail,
    Crt, Vortex, ZoomBlur, Fog,
    FxQuality,
)
from scena.collision import CollisionInfo
from scena.effects import HitFeedback
from scena.postfx import PostFxStack, PostEffectStage
from scena.orchestration import ScenaFramework
from scena.registry import TOP_LAYER
from scena.fx_quality import activate_quality, fidelity_is_survival


class TestPostFxStack(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        # radius_design / ripple radius assertions below assume identity view
        # (camera zoom × debug zoom == 1). Prior modules may leave zoom active.
        canvas.reset_view()
        ScenaFramework.get_instance()._set_debug_zoom(1.0)
        canvas.effects.clear()
        canvas.effects.enabled = True

    def tearDown(self):
        canvas.effects.clear()

    def test_impacts_never_join_the_authors_stack(self):
        # AC3 (game system tests): every impact (shake, flash, *_at) keeps its
        # internal HitFeedback in the render list; list(canvas.effects) and
        # len() showed it, though the Guia says impacts do not enter the stack.
        v = Vignette()
        for impact in (lambda: canvas.shake(4), lambda: canvas.flash(0.3),
                       lambda: canvas.hit_at((100, 100)), lambda: canvas.burst_at((50, 50))):
            impact()
            self.assertEqual(list(canvas.effects), [v])
            self.assertEqual(len(canvas.effects), 1)
            self.assertNotIn(canvas.effects._hit, canvas.effects)
            self.assertTrue(any(e is canvas.effects._hit for e in canvas.effects._effects))

    def test_add_remove_clear(self):
        stack = canvas.effects
        self.assertEqual(len(stack), 0)
        self.assertFalse(stack._is_active)
        v = stack.add(Vignette())
        self.assertEqual(len(stack), 1)
        self.assertTrue(stack._is_active)
        self.assertIs(stack.add(v), v)  # idempotent
        self.assertEqual(len(stack), 1)
        stack.remove(v)
        self.assertEqual(len(stack), 0)
        stack.add(Bloom())
        stack.clear()
        self.assertEqual(len(stack), 0)

    def test_add_rejects_look(self):
        from scena import Neon
        with self.assertRaises(TypeError):
            canvas.effects.add(Neon())

    def test_clear_releases_motion_trail_resources(self):
        trail = MotionTrail()
        trail._a = object()
        trail._b = object()
        trail._prev = object()
        trail._primed = True
        trail._size = (8, 8)
        canvas.effects.add(trail)
        canvas.effects.clear()
        self.assertIsNone(trail._a)
        self.assertIsNone(trail._b)
        self.assertIsNone(trail._prev)
        self.assertFalse(trail._primed)
        self.assertIsNone(trail._size)

    def test_clear_drops_runtime_children(self):
        from unittest.mock import patch
        canvas.effects.add(ColorWash())
        with patch("scena._sksl_effects.release_runtime_children") as rel:
            canvas.effects.clear()
            rel.assert_called()

    def test_remove_releases_motion_trail_resources(self):
        trail = MotionTrail()
        trail._prev = object()
        trail._primed = True
        canvas.effects.add(trail)
        canvas.effects.remove(trail)
        self.assertIsNone(trail._prev)
        self.assertFalse(trail._primed)

    def test_enabled_flag(self):
        canvas.effects.add(Vignette())
        self.assertTrue(canvas.effects._is_active)
        canvas.effects.enabled = False
        self.assertFalse(canvas.effects._is_active)
        canvas.effects.enabled = True

    def test_zero_arg_constructors(self):
        classes = (
            Vignette, Grain, Bloom, Grade, Chroma, Pixelate, Haze,
            Scanlines, ScreenBlur, Prism, Perspective, Lamp, GodRays, Spotlight,
            DistantLight, Kaleidoscope, Wash, MotionTrail,
            Crt, Vortex, ZoomBlur, Fog,
            ColorSweep, ColorWash, CosmicBloom,
        )
        for cls in classes:
            with self.subTest(cls=cls.__name__):
                e = cls()
                self.assertTrue(e.enabled)
                self.assertIsInstance(e._stage, PostEffectStage)
                key = e._fx_cache_key()
                self.assertIsInstance(key, tuple)

    def test_wash_look(self):
        w = Wash()
        self.assertGreater(w.intensity, 0)
        self.assertIsNotNone(w._build_color_filter())
        self.assertTrue(w._is_active())
        w.intensity = 0.0
        self.assertIsNone(w._build_color_filter())
        self.assertFalse(w._is_active())
        tinted = Wash(intensity=0.4, color="tomato")
        self.assertIsNotNone(tinted._build_color_filter())

    def test_motion_trail_defaults(self):
        t = MotionTrail()
        self.assertGreater(t.fade, 0)
        self.assertAlmostEqual(t.opacity, 1.0, places=3)
        self.assertEqual(len(t._fx_cache_key()), 3)
        self.assertNotIn("sharp", t._fx_cache_key())

    def _prime_motion_trail(self, trail):
        trail._a = object()
        trail._b = object()
        trail._prev = object()
        trail._primed = True
        trail._flip = 1
        trail._size = (8, 8)

    def _assert_motion_trail_history_empty(self, trail):
        self.assertIsNone(trail._a)
        self.assertIsNone(trail._b)
        self.assertIsNone(trail._prev)
        self.assertFalse(trail._primed)
        self.assertEqual(trail._flip, 0)
        self.assertIsNone(trail._size)

    def test_motion_trail_disable_drops_history(self):
        trail = MotionTrail()
        self._prime_motion_trail(trail)
        canvas.effects.add(trail)
        trail.enabled = False
        self.assertFalse(trail.enabled)
        self.assertFalse(trail._is_active())
        self._assert_motion_trail_history_empty(trail)
        trail.enabled = False  # idempotent
        self._assert_motion_trail_history_empty(trail)
        trail.enabled = True
        self.assertTrue(trail.enabled)
        self.assertTrue(trail._is_active())
        self._assert_motion_trail_history_empty(trail)

    def test_stack_disable_drops_motion_trail_history_on_render(self):
        import skia
        trail = MotionTrail()
        self._prime_motion_trail(trail)
        canvas.effects.add(trail)
        canvas.effects.enabled = False
        self.assertTrue(trail.enabled)  # instance still on; stack mute
        fw = ScenaFramework.get_instance()
        surf = skia.Surface(8, 8)
        img = surf.makeImageSnapshot()
        canvas.effects._render(surf.getCanvas(), img, fw=fw)
        self._assert_motion_trail_history_empty(trail)

    def test_motion_trail_skips_on_low_quality(self):
        from scena.fx_quality import active_fx_quality
        import skia
        prev = active_fx_quality()
        try:
            activate_quality(FxQuality.HIGH)
            self.assertFalse(fidelity_is_survival())
            activate_quality(FxQuality.LOW)
            self.assertTrue(fidelity_is_survival())
            t = MotionTrail()
            self._prime_motion_trail(t)
            surf = skia.Surface(8, 8)
            img = surf.makeImageSnapshot()
            t._draw_shader(surf.getCanvas(), img, 8, 8, 0.0, fw=None)
            self._assert_motion_trail_history_empty(t)
        finally:
            activate_quality(prev)

    def test_release_runtime_children_is_safe(self):
        from scena._sksl_effects import release_runtime_children
        from scena.effects import release_motion_trail_children
        release_runtime_children()
        release_motion_trail_children()

    def test_spotlight_has_range(self):
        s = Spotlight(range=200.0)
        self.assertEqual(s.range, 200.0)

    def test_grade_presets(self):
        for name in ("filmic", "cool", "warm", "sepia", "bw", "duo", "night"):
            g = Grade(name)
            cf = g._build_color_filter()
            self.assertIsNotNone(cf)

    def test_unknown_grade_preset_raises(self):
        with self.assertRaises(ValueError):
            Grade("neon")

    def test_haze_kinds(self):
        for kind in ("haze", "heat", "underwater"):
            h = Haze(kind=kind)
            self.assertEqual(h.kind, kind)
            self.assertGreater(h.amount, 0)
            self.assertIsInstance(h._fx_cache_key(), tuple)

    def test_unknown_haze_kind_raises(self):
        with self.assertRaises(ValueError):
            Haze(kind="fog")

    def test_glitch_transient(self):
        canvas.effects.clear()
        canvas.glitch()
        hit = canvas.effects._hit_feedback()
        self.assertGreaterEqual(hit._glitch, 1.0)
        self.assertTrue(hit._is_active())
        canvas.glitch(0.4)
        self.assertGreaterEqual(hit._glitch, 1.0)  # peak, not stack
        hit.tick_frame(0.1, canvas)
        self.assertLess(hit._glitch, 1.0)
        self.assertGreater(hit._glitch, 0.0)
        for _ in range(20):
            hit.tick_frame(0.2, canvas)
        self.assertLess(hit._glitch, 0.01)
        self.assertFalse(hit._is_active())

    def test_bloom_build_additive(self):
        b = Bloom()
        glow = b._build_additive(None, scale=0.5)
        self.assertIsNotNone(glow)
        b.intensity = 0
        self.assertIsNone(b._build_additive(None))

    def test_hit_feedback_api(self):
        canvas.flash(0.6)
        hit = canvas.effects._hit_feedback()
        self.assertIsInstance(hit, HitFeedback)
        self.assertGreater(hit._flash, 0)
        canvas.shake(12)
        self.assertGreaterEqual(hit._shake, 12)
        canvas.glitch(0.8)
        self.assertGreaterEqual(hit._glitch, 0.8)
        canvas.ripple_at(100, 200, amount=0.8)
        self.assertLess(hit._ripple_t, 0.1)
        self.assertAlmostEqual(hit._ripple_mode, 0.0)
        self.assertAlmostEqual(hit._ripple_span, 1.0)
        self.assertIsNone(hit._ripple_radius_design)
        self.assertTrue(hit._ripple_shock)
        self.assertGreater(hit._shake, 0.5)
        self.assertTrue(hit._is_active())
        # Default: no whiteout from ripple_at
        hit2_flash = hit._flash
        canvas.effects.clear()
        canvas.ripple_at(50, 50, amount=1.0, flash=True)
        hit = canvas.effects._hit_feedback()
        self.assertGreater(hit._flash, 0)
        canvas.effects.clear()
        canvas.ripple_at(40, 60, amount=0.5, radius=80)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._ripple_radius_design, 80.0)
        self.assertAlmostEqual(hit._ripple_span, 1.35 * 80.0 / 800.0)
        canvas.effects.clear()
        canvas.ripple_at(10, 20, shock=False)
        hit = canvas.effects._hit_feedback()
        self.assertFalse(hit._ripple_shock)
        self.assertLess(hit._ripple_t, 0.1)
        canvas.effects.clear()
        canvas.ripple_at(15, 25, shock=False, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertLess(hit._shake, 0.5)

    def test_wave_at_api(self):
        canvas.effects.clear()
        canvas.wave_at(200, 300, angle=90.0, amount=0.9)
        hit = canvas.effects._hit_feedback()
        self.assertLess(hit._ripple_t, 0.1)
        self.assertAlmostEqual(hit._ripple_mode, 1.0)
        self.assertTrue(hit._ripple_shock)
        self.assertGreater(hit._shake, 0.5)
        self.assertTrue(hit._is_active())
        canvas.effects.clear()
        canvas.wave_at(100, 100, shock=False)
        hit = canvas.effects._hit_feedback()
        self.assertFalse(hit._ripple_shock)
        self.assertLess(hit._ripple_t, 0.1)
        canvas.effects.clear()
        canvas.wave_at(80, 90, shock=False, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertLess(hit._shake, 0.5)

    def test_explosion_at_api(self):
        canvas.effects.clear()
        canvas.explosion_at(150, 250, amount=1.0)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 1)
        self.assertTrue(hit._bursts[0]["screen"])
        self.assertTrue(hit._bursts[0]["rings"])
        self.assertLess(hit._bursts[0]["t"], 0.1)
        self.assertLess(hit._ripple_t, 0.1)
        self.assertTrue(hit._is_active())
        # Default: no whiteout; camera shake on; shock smaller than ripple_at
        self.assertLess(hit._flash, 0.01)
        self.assertGreater(hit._shake, 0.5)
        self.assertAlmostEqual(hit._ripple_span, 0.4)
        canvas.effects.clear()
        canvas.explosion_at(10, 10, amount=1.0, shock=False)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 1)
        self.assertGreaterEqual(hit._ripple_t, 0.9)
        # shake=False skips camera
        canvas.effects.clear()
        canvas.explosion_at(20, 20, amount=1.0, shock=False, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 1)
        self.assertLess(hit._shake, 0.5)
        canvas.effects.clear()
        canvas.explosion_at(30, 30, amount=1.0, shock=False, shake=False, rings=True)
        hit = canvas.effects._hit_feedback()
        self.assertTrue(hit._bursts[0]["rings"])

    def test_burst_at_api(self):
        canvas.effects.clear()
        canvas.burst_at(100, 200, radius=36.0, amount=0.9)
        canvas.burst_at(300, 400, radius=24.0, amount=1.0)
        canvas.burst_at(500, 150, radius=48.0)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 3)
        self.assertFalse(hit._bursts[0]["screen"])
        self.assertFalse(hit._bursts[0]["rings"])
        self.assertAlmostEqual(hit._bursts[0]["radius_design"], 36.0)
        # Local: no shake / flash / shock by default
        self.assertLess(hit._shake, 0.5)
        self.assertLess(hit._flash, 0.01)
        self.assertGreaterEqual(hit._ripple_t, 0.9)
        self.assertTrue(hit._is_active())
        canvas.effects.clear()
        canvas.burst_at(80, 90, radius=20.0, rings=True)
        hit = canvas.effects._hit_feedback()
        self.assertTrue(hit._bursts[0]["rings"])

    def test_bubbles_at_api(self):
        canvas.effects.clear()
        canvas.bubbles_at(100, 200, color="cyan", count=12, height=80)
        canvas.bubbles(color="lime", count=20, columns=3)
        hit = canvas.effects._hit_feedback()
        self.assertGreaterEqual(len(hit._bubble_plumes), 4)  # 1 + 3 columns
        self.assertEqual(hit._bubble_plumes[0]["color"][1], 1.0)  # cyan mid channel ~1
        self.assertLess(hit._shake, 0.5)
        self.assertTrue(hit._is_active())
        # Plumes expire
        for _ in range(90):
            hit.tick_frame(0.02, canvas)
        self.assertEqual(len(hit._bubble_plumes), 0)

    def test_fireworks_at_api(self):
        from scena.fx_quality import activate_quality, active_fx_quality
        prev = active_fx_quality()
        activate_quality(FxQuality.HIGH)
        try:
            self._fireworks_at_api_body()
        finally:
            activate_quality(prev)

    def _fireworks_at_api_body(self):
        canvas.effects.clear()
        out = canvas.fireworks_at(100, 200, color="gold", radius=64.0, amount=1.0)
        self.assertIs(out, canvas)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._fireworks), 1)
        shell = hit._fireworks[0]
        self.assertAlmostEqual(shell["radius_design"], 64.0)
        self.assertAlmostEqual(shell["amount"], 1.0)
        self.assertEqual(len(shell["parts"]), 28)
        self.assertAlmostEqual(shell["fall"], 0.0)
        # Derived glitter is nearer white than the pigment
        self.assertGreater(shell["color2"][0], shell["color"][0] - 1e-6)
        self.assertGreater(shell["color2"][0], 0.7)
        self.assertLess(hit._shake, 0.5)
        self.assertLess(hit._flash, 0.01)
        self.assertGreaterEqual(hit._ripple_t, 0.9)
        self.assertTrue(hit._is_active())
        # Explicit fall / trail stored as written (clamped)
        canvas.effects.clear()
        canvas.fireworks_at(80, 90, fall=0.0, count=12, trail=0.5)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._fireworks[0]["fall"], 0.0)
        self.assertAlmostEqual(hit._fireworks[0]["trail"], 0.5)
        self.assertEqual(len(hit._fireworks[0]["parts"]), 12)
        canvas.effects.clear()
        canvas.fireworks_at(10, 10, fall=1.1, color="cyan", color2="white")
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._fireworks[0]["fall"], 1.1)
        self.assertAlmostEqual(hit._fireworks[0]["color2"][0], 1.0)
        # Clamp fall / count at spawn
        canvas.effects.clear()
        canvas.fireworks_at(0, 0, fall=9.0, count=200)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._fireworks[0]["fall"], 1.5)
        self.assertEqual(len(hit._fireworks[0]["parts"]), 48)
        canvas.effects.clear()
        canvas.fireworks_at(0, 0, fall=0.55, count=3)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._fireworks[0]["parts"]), 8)
        # Pool drops oldest
        canvas.effects.clear()
        for i in range(30):
            canvas.fireworks_at(i, 10, fall=0.55)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._fireworks), 24)
        # Expire
        canvas.effects.clear()
        canvas.fireworks_at(50, 50, fall=0.55)
        hit = canvas.effects._hit_feedback()
        dur = hit._fireworks[0]["duration"]
        self.assertGreaterEqual(dur, 0.85)
        self.assertLessEqual(dur, 1.70)
        for _ in range(int(dur / 0.02) + 6):
            hit.tick_frame(0.02, canvas)
        self.assertEqual(len(hit._fireworks), 0)
        self.assertFalse(hit._is_active())
        with self.assertRaises(TypeError):
            canvas.fireworks_at(0, 0, style="peony")

    def test_fireworks_at_particle_scale(self):
        from scena.fx_quality import activate_quality, active_fx_quality
        prev = active_fx_quality()
        try:
            activate_quality(FxQuality.LOW)
            canvas.effects.clear()
            canvas.fireworks_at(40, 40, count=28, fall=0.55)
            hit = canvas.effects._hit_feedback()
            n = len(hit._fireworks[0]["parts"])
            self.assertLessEqual(n, 20)
            self.assertGreaterEqual(n, 6)
        finally:
            activate_quality(prev)

    def test_fireworks_draw_ring_runs(self):
        import skia
        canvas.effects.clear()
        canvas.fireworks_at(100, 200, fall=0.55, trail=0.4)
        hit = canvas.effects._hit_feedback()
        hit.tick_frame(0.12, canvas)
        surf = skia.Surface(128, 128)
        hit.draw_ring(surf.getCanvas(), 128, 128)
        self.assertTrue(hit._is_active())

    def test_zap_at_api(self):
        from scena.fx_quality import activate_quality, active_fx_quality
        prev = active_fx_quality()
        activate_quality(FxQuality.HIGH)
        try:
            self._zap_at_api_body()
        finally:
            activate_quality(prev)

    def _zap_at_api_body(self):
        canvas.effects.clear()
        out = canvas.zap_at(100, 200, color="cyan", amount=1.0)
        self.assertIs(out, canvas)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._zaps), 1)
        zap = hit._zaps[0]
        self.assertEqual(zap["style"], "spark")
        self.assertAlmostEqual(zap["radius_design"], 24.0)
        self.assertAlmostEqual(zap["amount"], 1.0)
        self.assertEqual(len(zap["parts"]), 16)  # spark default count
        self.assertLess(hit._shake, 0.5)
        self.assertLess(hit._flash, 0.01)
        self.assertTrue(hit._is_active())
        # Explicit radius
        canvas.effects.clear()
        canvas.zap_at(0, 0, radius=48.0)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._zaps[0]["radius_design"], 48.0)
        # Styles + optional flash
        for style, n_default in (("spark", 16), ("fork", 8), ("corona", 12)):
            canvas.effects.clear()
            canvas.zap_at(10, 10, style=style)
            hit = canvas.effects._hit_feedback()
            self.assertEqual(hit._zaps[0]["style"], style)
            self.assertEqual(len(hit._zaps[0]["parts"]), n_default)
        canvas.effects.clear()
        canvas.zap_at(0, 0, style="fork", count=20, flash=True, amount=1.0)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._zaps[0]["parts"]), 20)
        self.assertGreater(hit._flash, 0.1)
        # Clamp count / radius; reject bad style
        canvas.effects.clear()
        canvas.zap_at(0, 0, count=200, radius=5.0)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._zaps[0]["parts"]), 36)
        self.assertAlmostEqual(hit._zaps[0]["radius_design"], 12.0)
        with self.assertRaises(ValueError):
            canvas.zap_at(0, 0, style="tesla")
        # Decay clears pool
        canvas.effects.clear()
        canvas.zap_at(50, 50, style="corona")
        hit = canvas.effects._hit_feedback()
        dur = hit._zaps[0]["duration"]
        for _ in range(int(dur / 0.02) + 6):
            hit.tick_frame(0.02, canvas)
        self.assertEqual(len(hit._zaps), 0)

    def test_zap_draw_ring_runs(self):
        import skia
        canvas.effects.clear()
        for style in ("spark", "fork", "corona"):
            canvas.zap_at(64, 64, style=style, radius=40.0)
        hit = canvas.effects._hit_feedback()
        hit.tick_frame(0.08, canvas)
        surf = skia.Surface(128, 128)
        hit.draw_ring(surf.getCanvas(), 128, 128)
        self.assertEqual(len(hit._zaps), 3)

    # -- hit_at / debris_at ------------------------------------------------

    def _at_quality(self, q, fn):
        from scena.fx_quality import activate_quality, active_fx_quality
        prev = active_fx_quality()
        activate_quality(q)
        try:
            return fn()
        finally:
            activate_quality(prev)

    def _render(self, hit, bg=(0, 0, 0, 255)):
        """Draw the hit-feedback overlays on an 800×600 plate; RGBA array."""
        import skia
        surf = skia.Surface(800, 600)
        c = surf.getCanvas()
        c.drawColor(skia.Color(bg[0], bg[1], bg[2], bg[3]))
        hit.draw_ring(c, 800, 600)
        return surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)

    def test_hit_at_api(self):
        self._at_quality(FxQuality.HIGH, self._hit_at_api_body)

    def _hit_at_api_body(self):
        canvas.effects.clear()
        out = canvas.hit_at(100, 200)
        self.assertIs(out, canvas)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._hits), 1)
        m = hit._hits[0]
        self.assertAlmostEqual(m["radius_design"], 16.0)
        self.assertAlmostEqual(m["amount"], 1.0)
        self.assertEqual(len(m["parts"]), 8)
        self.assertIsNone(m["angle_world"])
        self.assertLessEqual(m["duration"], 0.36)
        # A hit is local: no shake / flash / warp, no pyro.
        self.assertLess(hit._shake, 0.5)
        self.assertLess(hit._flash, 0.01)
        self.assertGreaterEqual(hit._ripple_t, 0.9)
        self.assertEqual(len(hit._bursts), 0)
        self.assertTrue(hit._is_active())
        # angle aims the sparks in a cone; None sprays all around.
        canvas.effects.clear()
        canvas.hit_at(0, 0, angle=90, count=12)
        offs = [p["off"] for p in canvas.effects._hit_feedback()._hits[0]["parts"]]
        self.assertLess(max(abs(o) for o in offs), math.radians(65))
        canvas.effects.clear()
        canvas.hit_at(0, 0, count=12)
        offs = [p["off"] for p in canvas.effects._hit_feedback()._hits[0]["parts"]]
        self.assertGreater(max(offs) - min(offs), math.pi * 1.5)
        # Clamps: radius, count.
        canvas.effects.clear()
        canvas.hit_at(0, 0, radius=2.0, count=200)
        m = canvas.effects._hit_feedback()._hits[0]
        self.assertAlmostEqual(m["radius_design"], 6.0)
        self.assertEqual(len(m["parts"]), 24)
        # Pool keeps the newest 64 (a boss under a stream of shots).
        canvas.effects.clear()
        for i in range(80):
            canvas.hit_at(i, 10)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._hits), 64)
        self.assertAlmostEqual(hit._hits[-1]["world"][0], 79.0)
        # Expires on its own.
        canvas.effects.clear()
        canvas.hit_at(50, 50, color="cyan")
        hit = canvas.effects._hit_feedback()
        dur = hit._hits[0]["duration"]
        for _ in range(int(dur / 0.02) + 4):
            hit.tick_frame(0.02, canvas)
        self.assertEqual(len(hit._hits), 0)
        self.assertFalse(hit._is_active())

    def test_hit_at_locus_grammar(self):
        canvas.effects.clear()
        hit = canvas.effects._hit_feedback()
        self.assertIs(canvas.hit_at(None), canvas)
        exit_info = CollisionInfo(a=None, b=None, normal=Vec2.temp(0, 0), depth=0.0, points=[])
        canvas.hit_at(exit_info, angle=90)
        self.assertEqual(len(hit._hits), 0)
        info = CollisionInfo(
            a=None, b=None, normal=Vec2.temp(0, 1), depth=1.0, points=[(150.0, 250.0)],
        )
        canvas.hit_at(info)
        self.assertEqual(hit._hits[-1]["world"], (150.0, 250.0))
        # The contact normal is never read: the sparks stay all-around.
        self.assertIsNone(hit._hits[-1]["angle_world"])
        canvas.hit_at(Circle(center=(120, 80), radius=10))
        self.assertEqual(hit._hits[-1]["world"], (120.0, 80.0))
        canvas.hit_at((30, 40), angle=0)
        self.assertEqual(hit._hits[-1]["world"], (30.0, 40.0))

    def test_hit_at_rejects_bad_knobs(self):
        for kw in (
            {"radius": "big"}, {"amount": True}, {"angle": "up"},
            {"angle": lambda: 90}, {"count": 2.5}, {"color": 3},
        ):
            with self.subTest(kw=kw), self.assertRaises(TypeError):
                canvas.hit_at(10, 10, **kw)
        for kw in (
            {"radius": 0}, {"amount": -1}, {"count": -1},
            {"style": "flash"}, {"style": None}, {"style": 3},
            # A disc has no sparks and no direction: never silently ignored.
            {"style": "disc", "count": 0}, {"style": "disc", "count": 8},
            {"style": "disc", "angle": 90},
        ):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                canvas.hit_at(10, 10, **kw)
        # Knobs are checked even when the locus is a no-op.
        with self.assertRaises(TypeError):
            canvas.hit_at(None, radius="big")
        with self.assertRaises(ValueError):
            canvas.hit_at(None, style="disc", angle=90)
        with self.assertRaises(ValueError):
            canvas.hit_at(None, style="flash")

    def _lit(self, hit, t=0.05):
        hit.tick_frame(t, canvas)
        return self._render(hit).astype(float)[..., :3].sum(axis=2) > 30.0

    def test_hit_at_count_zero_keeps_star_without_sparks(self):
        for q in (FxQuality.LOW, FxQuality.MEDIUM, FxQuality.HIGH):
            def body():
                canvas.effects.clear()
                canvas.hit_at(400, 300, radius=40, count=0, angle=90)
                hit = canvas.effects._hit_feedback()
                h = hit._hits[0]
                self.assertEqual(h["style"], "star")
                # Quality scaling never adds sparks back.
                self.assertEqual(h["parts"], [])
                self.assertGreater(int(self._lit(hit).sum()), 0)
                canvas.effects.clear()
                canvas.hit_at(400, 300)
                self.assertGreaterEqual(len(canvas.effects._hit_feedback()._hits[0]["parts"]), 3)
            with self.subTest(q=q):
                self._at_quality(q, body)

    def test_hit_at_default_count_is_eight_sparks(self):
        def body():
            canvas.effects.clear()
            canvas.hit_at(400, 300)
            self.assertEqual(len(canvas.effects._hit_feedback()._hits[0]["parts"]), 8)
        self._at_quality(FxQuality.HIGH, body)

    def test_hit_at_disc_is_a_round_pop_at_every_quality(self):
        """``style="disc"``: no sparks, round, and visible even at LOW
        (survival), where the star's soft glow is skipped."""
        for q in (FxQuality.LOW, FxQuality.MEDIUM, FxQuality.HIGH):
            def body():
                canvas.effects.clear()
                self.assertIs(canvas.hit_at(400, 300, style="Disc", radius=40), canvas)
                hit = canvas.effects._hit_feedback()
                h = hit._hits[0]
                self.assertEqual(h["style"], "disc")
                self.assertEqual(h["parts"], [])
                lit = self._lit(hit)
                ys, xs = lit.nonzero()
                self.assertGreater(len(xs), 0)
                w = xs.max() - xs.min() + 1
                hh = ys.max() - ys.min() + 1
                self.assertLessEqual(abs(int(w) - int(hh)), 2)
                # A filled circle covers ~pi/4 of its box; a star far less.
                self.assertGreater(lit.sum() / float(w * hh), 0.7)
                self.assertLess(abs((xs.min() + xs.max()) / 2.0 - 400.0), 2.0)
                # Same lifetime as the star; then it is gone.
                for _ in range(int(h["duration"] / 0.02) + 4):
                    hit.tick_frame(0.02, canvas)
                self.assertEqual(len(hit._hits), 0)
            with self.subTest(q=q):
                self._at_quality(q, body)

    def test_hit_at_angle_points_up_on_screen(self):
        """``angle=90`` is world-up (y-up). The FB is y-down: a missed flip
        sprays the sparks into the hero instead of back at the shooter."""
        def body():
            canvas.effects.clear()
            canvas.hit_at(400, 300, angle=90, radius=40, count=12)
            hit = canvas.effects._hit_feedback()
            self.assertAlmostEqual(hit._hits[0]["angle_fb"], -math.pi / 2, places=6)
            hit.tick_frame(0.10, canvas)
            px = self._render(hit).astype(float)[..., :3].sum(axis=2)
            above = px[:280].sum()
            below = px[320:].sum()
            self.assertGreater(above, 2.0 * below)
        self._at_quality(FxQuality.HIGH, body)

    def test_hit_draw_runs_every_quality(self):
        for q in (FxQuality.LOW, FxQuality.MEDIUM, FxQuality.HIGH):
            def body():
                canvas.effects.clear()
                canvas.hit_at(100, 100, angle=45)
                canvas.hit_at(200, 100, color="cyan")
                hit = canvas.effects._hit_feedback()
                for t in (0.0, 0.05, 0.1):
                    hit.tick_frame(0.05 if t else 0.0, canvas)
                    px = self._render(hit)
                self.assertGreater(int(px[..., :3].max()), 0)
            with self.subTest(q=q):
                self._at_quality(q, body)

    def test_debris_at_api(self):
        self._at_quality(FxQuality.HIGH, self._debris_at_api_body)

    def _debris_at_api_body(self):
        canvas.effects.clear()
        out = canvas.debris_at(100, 200)
        self.assertIs(out, canvas)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._debris), 1)
        d = hit._debris[0]
        self.assertAlmostEqual(d["radius_design"], 40.0)
        self.assertEqual(len(d["parts"]), 14)
        self.assertAlmostEqual(d["fall"], 0.0)
        self.assertTrue(d["dust"])
        for part in d["parts"]:
            self.assertIn(len(part["verts"]), (3, 4, 5))
        # Not pyro, no camera feedback.
        self.assertEqual(len(hit._bursts), 0)
        self.assertLess(hit._shake, 0.5)
        self.assertLess(hit._flash, 0.01)
        # Clamps.
        canvas.effects.clear()
        canvas.debris_at(0, 0, count=500, fall=9.0, radius=1.0)
        d = canvas.effects._hit_feedback()._debris[0]
        self.assertEqual(len(d["parts"]), 40)
        self.assertAlmostEqual(d["fall"], 1.5)
        self.assertAlmostEqual(d["radius_design"], 10.0)
        # Pool cap + expiry.
        canvas.effects.clear()
        for i in range(20):
            canvas.debris_at(i, 0)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._debris), 16)
        for _ in range(int(1.4 / 0.02) + 4):
            hit.tick_frame(0.02, canvas)
        self.assertEqual(len(hit._debris), 0)
        self.assertFalse(hit._is_active())

    def test_debris_at_rejects_bad_knobs(self):
        for kw in (
            {"radius": "big"}, {"amount": "x"}, {"count": 3.5}, {"fall": None},
            {"dust": "yes"}, {"color": 7},
        ):
            with self.subTest(kw=kw), self.assertRaises(TypeError):
                canvas.debris_at(10, 10, **kw)
        for kw in ({"radius": -5}, {"fall": -1}, {"count": 0}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                canvas.debris_at(10, 10, **kw)
        self.assertIs(canvas.debris_at(None), canvas)

    def test_debris_fall_pulls_shards_down(self):
        from scena.effects import _debris_offset
        part = {"ang": math.pi / 2, "speed": 1.0, "g": 1.0}
        _x0, y_drift = _debris_offset(part, 0.6, 40.0, 0.0, 1.0)
        _x1, y_fall = _debris_offset(part, 0.6, 40.0, 1.0, 1.0)
        self.assertGreater(y_drift, 0.0)
        self.assertLess(y_fall, y_drift - 20.0)
        # Drag: the spray slows down (distance grows less in the second half).
        _, y_a = _debris_offset(part, 0.3, 40.0, 0.0, 1.0)
        self.assertGreater(y_a, 0.5 * y_drift)

    def test_debris_is_matte_not_emissive(self):
        """Debris paints with normal blending: on a white plate it darkens.
        An additive (Plus) shard would vanish on bright backgrounds."""
        def body():
            canvas.effects.clear()
            canvas.debris_at(400, 300, radius=60, dust=False)
            hit = canvas.effects._hit_feedback()
            hit.tick_frame(0.15, canvas)
            px = self._render(hit, bg=(255, 255, 255, 255))
            self.assertLess(int(px[..., :3].min()), 200)
        self._at_quality(FxQuality.HIGH, body)

    def test_debris_particle_scale_and_low_quality_draw(self):
        def body():
            canvas.effects.clear()
            canvas.debris_at(400, 300, count=28)
            hit = canvas.effects._hit_feedback()
            n = len(hit._debris[0]["parts"])
            self.assertLess(n, 28)
            self.assertGreaterEqual(n, 4)
            hit.tick_frame(0.1, canvas)
            px = self._render(hit, bg=(255, 255, 255, 255))
            self.assertLess(int(px[..., :3].min()), 230)
        self._at_quality(FxQuality.LOW, body)

    def test_burst_and_explosion_have_no_recipe(self):
        """``recipe="flash"`` (an orange disc-only pop) was retired for ``hit_at``."""
        for verb in (canvas.burst_at, canvas.explosion_at):
            with self.subTest(verb=verb.__name__), self.assertRaises(TypeError):
                verb(10, 10, recipe="flash")
        canvas.effects.clear()
        canvas.burst_at(10, 10)
        canvas.explosion_at(20, 20, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertTrue(all("recipe" not in b for b in hit._bursts))
        self.assertLess(hit._ripple_t, 0.9)  # shock always runs now

    def test_act_change_clears_hit_and_debris(self):
        canvas.hit_at(10, 10)
        canvas.debris_at(10, 10)
        hit = canvas.effects._hit_feedback()
        hit._clear_pulses()
        self.assertEqual((len(hit._hits), len(hit._debris)), (0, 0))

    def test_top_layer_post_fx_toggle(self):
        canvas.layers["top"].post_fx = False
        layer = canvas._engine.registry.layers.get(TOP_LAYER)
        self.assertTrue(layer._exempt_from_post)
        canvas.layers["top"].post_fx = True
        self.assertFalse(layer._exempt_from_post)
        with self.assertRaises(ValueError):
            canvas.layers["default"].post_fx = False

    def test_identity_passthrough_empty(self):
        """Empty stack is not active → orchestration should skip scene RT."""
        canvas.effects.clear()
        fw = ScenaFramework.get_instance()
        self.assertFalse(fw._builtin_post_active())
        canvas.effects.add(Vignette())
        self.assertTrue(fw._builtin_post_active())

    def test_filter_build_chain(self):
        stack = PostFxStack()
        stack.add(Pixelate())
        stack.add(Chroma())
        by_stage = {s: [] for s in PostEffectStage}
        for e in stack:
            by_stage[e._stage].append(e)
        filt = stack._build_replace_filter(by_stage, scale=1.0, phase=0.0)
        self.assertIsNotNone(filt)


class TestDrawLayerFilter(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        from scena import Circle
        # clear registry shapes if any leftover from other tests is hard;
        # just add on top / default
        self.c_default = Circle(center=(50, 50), radius=10)
        self.c_top = Circle(center=(100, 100), radius=10, layer="top")

    def test_layer_filter_predicate(self):
        eng = canvas._engine
        names = []

        def capture(name):
            names.append(name)
            return True

        # Monkey: wrap draw to record which layers are visited via filter
        visited = []
        orig = eng.draw

        def wrapped(layer_filter=None):
            for layer in eng.registry.layers.iter_draw_order():
                if layer_filter is not None and not layer_filter(layer.name):
                    continue
                visited.append(layer.name)

        eng.draw = wrapped
        try:
            eng.draw(layer_filter=lambda n: n != "top")
            self.assertNotIn("top", visited)
            self.assertIn("default", visited)
            visited.clear()
            eng.draw(layer_filter=lambda n: n == "top")
            self.assertEqual(visited, ["top"])
        finally:
            eng.draw = orig


class TestSpatialColorWashes(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        canvas.effects.clear()

    def tearDown(self):
        canvas.effects.clear()

    def test_colorsweep_axis_and_palette(self):
        e = ColorSweep()
        self.assertEqual(e.axis, "radial")
        self.assertEqual(len(e.colors), 3)
        self.assertAlmostEqual(e.speed, 1.0, places=3)
        e.axis = "horizontal"
        self.assertEqual(e.axis, "horizontal")
        e.axis = 2
        self.assertEqual(e.axis, "vertical")
        e.colors = ("tomato", "navy")
        self.assertEqual(len(e.colors), 2)
        four = ColorSweep(colors=("cyan", "magenta", "gold", "lime"), axis="vertical")
        self.assertEqual(four.axis, "vertical")
        self.assertEqual(len(four.colors), 4)

    def test_plasmawash_two_and_three(self):
        two = ColorWash(color="gold", color2="navy")
        self.assertEqual(len(two.colors), 2)
        three = ColorWash()
        self.assertEqual(len(three.colors), 3)

    def test_nebulabloom_named_colors(self):
        from scena.color import Color
        n = CosmicBloom(color="orchid", color2="cyan")
        expected = tuple(float(c) for c in Color("orchid").rgb[:3])
        self.assertEqual(n.color, expected)
        self.assertEqual(n.color2, (0.0, 1.0, 1.0))
        d = CosmicBloom()
        self.assertAlmostEqual(d.amount, 1.0, places=3)
        self.assertAlmostEqual(d.speed, 1.2, places=3)


class TestHitAtArity(unittest.TestCase):
    """canvas.*_at dual arity: (x, y) or one point-like; None is a no-op."""

    def setUp(self):
        init(width=800, height=600)
        canvas.reset_view()
        ScenaFramework.get_instance()._set_debug_zoom(1.0)
        canvas.effects.clear()
        canvas.effects.enabled = True

    def tearDown(self):
        canvas.effects.clear()

    def test_explosion_at_tuple_and_keywords(self):
        canvas.explosion_at((150, 250), amount=1.0, shock=False, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 1)
        uv = hit._bursts[0]["uv"]
        self.assertAlmostEqual(uv[0], 150 / 800, places=4)

    def test_explosion_at_none_is_noop(self):
        canvas.explosion_at(None, amount=1.0)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 0)
        self.assertIs(canvas.explosion_at(None), canvas)

    def test_explosion_at_collision_info(self):
        info = CollisionInfo(
            a=None, b=None, normal=Vec2.temp(1, 0), depth=1.0,
            points=[(150.0, 250.0)],
        )
        canvas.explosion_at(info, amount=1.0, shock=False, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 1)
        canvas.effects.clear()
        canvas.explosion_at(info.point, amount=1.0, shock=False, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 1)

    def test_explosion_at_exit_info_is_noop(self):
        info = CollisionInfo(
            a=None, b=None, normal=Vec2.temp(0, 0), depth=0.0, points=[],
        )
        self.assertIsNone(info.point)
        canvas.explosion_at(info, amount=1.0)
        canvas.explosion_at(info.point, amount=1.0)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 0)

    def test_explosion_at_touching_contact(self):
        from scena.collision import TouchingContact
        tc = TouchingContact(
            other=None, side="bottom", slope_angle=0.0,
            normal=Vec2.temp(0, 1), tangent=Vec2.temp(1, 0),
            point=(150.0, 250.0),
        )
        canvas.explosion_at(tc, amount=1.0, shock=False, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 1)

    def test_burst_at_graphic(self):
        ship = Circle(center=(100, 200), radius=12)
        canvas.burst_at(ship, radius=36.0)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 1)
        self.assertFalse(hit._bursts[0]["screen"])
        ship.destroy()

    def test_burst_at_point_object(self):
        p = Point(40, 60)
        canvas.burst_at(p, radius=20.0)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._bursts), 1)
        p.destroy()

    def test_ripple_at_vec2(self):
        canvas.ripple_at(Vec2(100, 200), amount=0.5, shock=False, shake=False)
        hit = canvas.effects._hit_feedback()
        self.assertLess(hit._ripple_t, 0.1)

    def test_zap_at_graphic(self):
        ship = Circle(center=(100, 200), radius=12)
        canvas.zap_at(ship, style="fork", radius=30.0)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._zaps), 1)
        self.assertEqual(hit._zaps[0]["style"], "fork")
        self.assertAlmostEqual(hit._zaps[0]["radius_design"], 30.0)
        ship.destroy()

    def test_zap_at_none_is_noop(self):
        canvas.zap_at(None)
        hit = canvas.effects._hit_feedback()
        self.assertEqual(len(hit._zaps), 0)
        self.assertIs(canvas.zap_at(None), canvas)

    def test_bad_locus_raises(self):
        with self.assertRaises(TypeError):
            canvas.explosion_at("nope")

    # Every one-shot point verb: (verb, knobs that must raise TypeError,
    # knobs that must raise ValueError). The engine only float()s / int()s,
    # which leaked Python's message for strings and took True as 1.
    _POINT_VERB_BAD_KNOBS = {
        "ripple_at": (
            [{"amount": "x"}, {"amount": True}, {"amount": lambda: 1},
             {"radius": "big"}, {"radius": False}, {"shock": "no"},
             {"flash": None}, {"shake": 2.0}],
            [{"amount": -1}, {"radius": 0}, {"radius": -5}],
        ),
        "wave_at": (
            [{"angle": "up"}, {"angle": True}, {"angle": lambda: 90},
             {"amount": None}, {"shock": "yes"}, {"shake": None}],
            [{"amount": -0.5}],
        ),
        "explosion_at": (
            [{"amount": "x"}, {"amount": True}, {"rings": "no"},
             {"flash": None}, {"shock": 1.0}],
            [{"amount": -1}],
        ),
        "burst_at": (
            [{"radius": "x"}, {"radius": True}, {"amount": lambda: 1},
             {"rings": None}],
            [{"radius": 0}, {"radius": -1}, {"amount": -1}],
        ),
        "bubbles_at": (
            [{"count": "a"}, {"count": 2.5}, {"count": True},
             {"height": "tall"}, {"amount": None}],
            [{"count": 0}, {"height": 0}, {"amount": -1}],
        ),
        "fireworks_at": (
            [{"radius": "x"}, {"count": "a"}, {"count": 12.0},
             {"fall": True}, {"trail": "long"}, {"amount": lambda: 1}],
            [{"radius": -1}, {"count": 0}, {"fall": -1}, {"trail": -0.1}],
        ),
        "zap_at": (
            [{"radius": "x"}, {"amount": True}, {"count": "a"},
             {"count": 4.0}, {"flash": "no"}],
            [{"radius": 0}, {"amount": -1}, {"count": 0}, {"style": "tesla"},
             {"style": 3}],
        ),
    }

    def test_point_verbs_reject_bad_knobs(self):
        for name, (type_errs, value_errs) in self._POINT_VERB_BAD_KNOBS.items():
            verb = getattr(canvas, name)
            for kw in type_errs:
                with self.subTest(verb=name, kw=kw), self.assertRaises(TypeError) as cm:
                    verb(10, 10, **kw)
                self.assertIn(next(iter(kw)), str(cm.exception))  # names the knob
                # Knobs are checked even when the locus is a no-op.
                with self.subTest(verb=name, kw=kw, locus=None), self.assertRaises(TypeError):
                    verb(None, **kw)
            for kw in value_errs:
                with self.subTest(verb=name, kw=kw), self.assertRaises(ValueError):
                    verb(10, 10, **kw)
                with self.subTest(verb=name, kw=kw, locus=None), self.assertRaises(ValueError):
                    verb(None, **kw)
        canvas.effects.clear()

    def test_bubbles_rejects_bad_knobs(self):
        for kw in ({"count": "a"}, {"count": 2.5}, {"columns": True},
                   {"columns": 3.0}, {"height": "tall"}, {"amount": None},
                   {"amount": lambda: 1}):
            with self.subTest(kw=kw), self.assertRaises(TypeError) as cm:
                canvas.bubbles(**kw)
            self.assertIn(f"canvas.bubbles {next(iter(kw))}", str(cm.exception))
        for kw in ({"count": 0}, {"columns": 0}, {"height": -1}, {"amount": -1}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                canvas.bubbles(**kw)
        canvas.effects.clear()

    def test_point_verbs_accept_valid_knobs(self):
        """0/1 read as flags, ints as numbers; engine clamps still apply."""
        canvas.effects.clear()
        canvas.ripple_at(10, 10, amount=0, radius=40, shock=0, flash=1, shake=0)
        canvas.wave_at(10, 10, angle=-45, amount=1, shock=1, flash=0, shake=0)
        canvas.explosion_at(10, 10, amount=0.5, shock=0, shake=0, rings=1)
        canvas.burst_at(10, 10, radius=1, amount=0)
        canvas.bubbles_at(10, 10, count=1, height=1)
        canvas.fireworks_at(10, 10, count=1, fall=0, trail=5)
        canvas.zap_at(10, 10, count=None, flash=0)
        canvas.bubbles(count=1, columns=1)
        hit = canvas.effects._hit_feedback()
        self.assertAlmostEqual(hit._fireworks[0]["trail"], 1.0)
        self.assertEqual(len(hit._zaps), 1)
        canvas.effects.clear()


class TestPostFxHeadless(unittest.TestCase):
    """With no GL context the scene / FX render targets are raster surfaces:
    every exported post effect draws headless and changes the frame."""

    def test_every_post_effect_draws_without_gl(self):
        import inspect
        import numpy as np
        import skia
        import scena
        from scena.postfx import PostEffect
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from system_support import system_world

        names = [n for n in scena.__all__
                 if inspect.isclass(getattr(scena, n, None))
                 and issubclass(getattr(scena, n), PostEffect)
                 and getattr(scena, n) is not PostEffect]
        self.assertGreaterEqual(len(names), 20)

        def screen(w):
            a = np.asarray(w.surface.makeImageSnapshot().toarray(
                colorType=skia.kRGBA_8888_ColorType))
            return a[: int(canvas.height), : int(canvas.width)].astype(int)

        with system_world(draw=True) as w:
            self.assertIsNone(w.fw._context)
            hero = Circle(center=(canvas.width / 2, canvas.height / 2),
                          radius=min(canvas.width, canvas.height) / 3, color="tomato")
            w.step(3)
            base = screen(w)
            for name in names:
                with self.subTest(name):
                    canvas.effects.clear()
                    canvas.effects.add(getattr(scena, name)())
                    if name == "MotionTrail":   # trails need motion
                        hero.move_by(40, 0)
                    w.step(3)
                    self.assertGreater(int(np.abs(screen(w) - base).max()), 8)
                    if name == "MotionTrail":
                        hero.move_by(-40, 0)
                        w.step(3)
            canvas.effects.clear()


if __name__ == "__main__":
    unittest.main()
