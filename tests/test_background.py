"""
Unit tests for the pre-scene BackgroundField system (parallax math + stack API).
"""
import unittest

from scena.background import (
    BackgroundField,
    BackgroundStack,
    CameraSample,
    parallax_transform,
    vanishing_point_offset,
)
from scena.background_kinds import (
    Wallpaper, SkyGradient, sky_palette,
    Clouds,
    Stars, Stardust, Chromadust, Nebuladust, Borealis, Plasma, Mist,
    Debris, Embers, WindStreaks, Ground, Lattice, Nebula,
    Floor, Road,
    Tunnel, StarFly, PlanetFly,
    ChurningClouds, FilamentField,
    _radial_fly_uv,
    HORIZON_FADE,
)
from scena.place import unplaced_creation


class _UnplacedTest(unittest.TestCase):
    """Construct fields without attaching them to the live canvas stack."""

    def setUp(self):
        self._unplaced = unplaced_creation()
        self._unplaced.__enter__()

    def tearDown(self):
        self._unplaced.__exit__(None, None, None)


class TestParallaxTransform(unittest.TestCase):
    def test_screen_locked_zero_offset_and_scale_identity(self):
        ox, oy, scale, rot = parallax_transform(
            pan_x=800.0,
            pan_y=900.0,
            zoom=3.0,
            rotation_deg=45.0,
            design_width=1000.0,
            design_height=800.0,
            fb_width=2000.0,
            fb_height=1600.0,
            pan_response=0.0,
            zoom_response=0.0,
            rotation_response=0.0,
        )
        self.assertAlmostEqual(ox, 0.0)
        self.assertAlmostEqual(oy, 0.0)
        self.assertAlmostEqual(scale, 1.0)
        self.assertAlmostEqual(rot, 0.0)

    def test_full_response_tracks_pan_and_zoom(self):
        # rest = design center (500, 400); pan to (600, 500): Δ = (+100, +100)
        # device scale = 2; camera zoom = 2 → pixel offset |Δ|·zoom·device = 400
        ox, oy, scale, rot = parallax_transform(
            pan_x=600.0,
            pan_y=500.0,
            zoom=2.0,
            rotation_deg=0.0,
            design_width=1000.0,
            design_height=800.0,
            fb_width=2000.0,
            fb_height=1600.0,
            pan_response=1.0,
            zoom_response=1.0,
            rotation_response=0.0,
        )
        self.assertAlmostEqual(ox, -400.0)
        self.assertAlmostEqual(oy, 400.0)
        self.assertAlmostEqual(scale, 2.0)
        self.assertAlmostEqual(rot, 0.0)

    def test_half_pan_response_and_zoom_lerp(self):
        ox, oy, scale, _ = parallax_transform(
            pan_x=600.0,
            pan_y=500.0,
            zoom=2.0,
            rotation_deg=0.0,
            design_width=1000.0,
            design_height=800.0,
            fb_width=2000.0,
            fb_height=1600.0,
            pan_response=0.5,
            zoom_response=0.5,
        )
        self.assertAlmostEqual(ox, -200.0)
        self.assertAlmostEqual(oy, 200.0)
        self.assertAlmostEqual(scale, 1.5)

    def test_pan_same_direction_as_content_when_look_increases(self):
        """Increasing look-at must produce negative screen-X offset (content left)."""
        ox_left, _, _, _ = parallax_transform(
            pan_x=600.0, pan_y=400.0, zoom=1.0, rotation_deg=0.0,
            design_width=1000.0, design_height=800.0,
            fb_width=1000.0, fb_height=800.0,
            pan_response=1.0, zoom_response=0.0,
        )
        ox_id, _, _, _ = parallax_transform(
            pan_x=500.0, pan_y=400.0, zoom=1.0, rotation_deg=0.0,
            design_width=1000.0, design_height=800.0,
            fb_width=1000.0, fb_height=800.0,
            pan_response=1.0, zoom_response=0.0,
        )
        self.assertLess(ox_left, ox_id)
        self.assertAlmostEqual(ox_left, -100.0)

    def test_center_origin_rest_zero_offset_regardless_of_pan_response(self):
        """set_origin('center') rest = (0,0): pan_response must not rebake placement."""
        for p in (0.0, 0.3, 1.0):
            ox, oy, scale, _ = parallax_transform(
                pan_x=0.0,
                pan_y=0.0,
                zoom=1.0,
                rotation_deg=0.0,
                design_width=1400.0,
                design_height=900.0,
                fb_width=1400.0,
                fb_height=900.0,
                pan_response=p,
                zoom_response=0.0,
                rest_x=0.0,
                rest_y=0.0,
            )
            self.assertAlmostEqual(ox, 0.0, msg=f"pan_response={p}")
            self.assertAlmostEqual(oy, 0.0, msg=f"pan_response={p}")
            self.assertAlmostEqual(scale, 1.0)

    def test_center_origin_pan_delta_matches_shapes(self):
        # rest (0,0); look moves +100 in X → content left → offset_x = -100
        ox, oy, _, _ = parallax_transform(
            pan_x=100.0,
            pan_y=0.0,
            zoom=1.0,
            rotation_deg=0.0,
            design_width=1400.0,
            design_height=900.0,
            fb_width=1400.0,
            fb_height=900.0,
            pan_response=1.0,
            zoom_response=0.0,
            rest_x=0.0,
            rest_y=0.0,
        )
        self.assertAlmostEqual(ox, -100.0)
        self.assertAlmostEqual(oy, 0.0)

    def test_rotation_response(self):
        """rotation_rad is camera-matching CCW+ (same sense as world content)."""
        _, _, _, rot = parallax_transform(
            pan_x=500.0,
            pan_y=400.0,
            zoom=1.0,
            rotation_deg=90.0,
            design_width=1000.0,
            design_height=800.0,
            fb_width=1000.0,
            fb_height=800.0,
            pan_response=0.0,
            zoom_response=0.0,
            rotation_response=1.0,
        )
        import math
        self.assertAlmostEqual(rot, math.pi / 2, places=5)

    def test_rotation_response_scales_fraction(self):
        _, _, _, rot = parallax_transform(
            pan_x=500.0,
            pan_y=400.0,
            zoom=1.0,
            rotation_deg=90.0,
            design_width=1000.0,
            design_height=800.0,
            fb_width=1000.0,
            fb_height=800.0,
            pan_response=0.0,
            zoom_response=0.0,
            rotation_response=0.5,
        )
        import math
        self.assertAlmostEqual(rot, math.pi / 4, places=5)

    def test_identity_look_at_center_gives_zero_offset(self):
        ox, oy, scale, _ = parallax_transform(
            pan_x=500.0,
            pan_y=400.0,
            zoom=1.0,
            rotation_deg=0.0,
            design_width=1000.0,
            design_height=800.0,
            fb_width=2000.0,
            fb_height=1600.0,
            pan_response=1.0,
            zoom_response=1.0,
        )
        self.assertAlmostEqual(ox, 0.0)
        self.assertAlmostEqual(oy, 0.0)
        self.assertAlmostEqual(scale, 1.0)


class TestVanishingPointOffset(unittest.TestCase):
    def test_center_at_rest_is_screen_center(self):
        ox, oy = vanishing_point_offset(
            center_x=0.0, center_y=0.0,
            rest_x=0.0, rest_y=0.0,
            design_width=1400.0, design_height=900.0,
            fb_width=1400.0, fb_height=900.0,
        )
        self.assertAlmostEqual(ox, 0.0)
        self.assertAlmostEqual(oy, 0.0)

    def test_right_of_rest_positive_x_y_up_flips(self):
        # device scale 2; +100 design X → +200 FB; +80 design Y → −160 FB
        ox, oy = vanishing_point_offset(
            center_x=100.0, center_y=80.0,
            rest_x=0.0, rest_y=0.0,
            design_width=1000.0, design_height=800.0,
            fb_width=2000.0, fb_height=1600.0,
        )
        self.assertAlmostEqual(ox, 200.0)
        self.assertAlmostEqual(oy, -160.0)

    def test_corner_origin_rest_is_design_center(self):
        ox, oy = vanishing_point_offset(
            center_x=500.0, center_y=400.0,
            rest_x=500.0, rest_y=400.0,
            design_width=1000.0, design_height=800.0,
            fb_width=1000.0, fb_height=800.0,
        )
        self.assertAlmostEqual(ox, 0.0)
        self.assertAlmostEqual(oy, 0.0)


class TestBackgroundRoundTrip(unittest.TestCase):
    """canvas.background reads the live stack; writing it back keeps it (it raised
    TypeError: a write expected a material). Saving the base restores it later."""

    def test_round_trip(self):
        from scena import canvas, SkyGradient
        stack = canvas.background
        base = stack.base
        items = list(stack)
        canvas.background = canvas.background
        self.assertIs(canvas.background, stack)
        self.assertIs(canvas.background.base, base)
        self.assertEqual(list(canvas.background), items)
        saved = canvas.background.base
        canvas.background = "navy"
        canvas.background = saved
        self.assertIs(canvas.background.base, saved)


class TestBackgroundStack(_UnplacedTest):
    def test_empty_stack_inactive(self):
        stack = BackgroundStack()
        self.assertEqual(len(stack), 0)
        self.assertFalse(stack._is_active)

    def test_add_remove_clear(self):
        stack = BackgroundStack()
        sky = Clouds()
        stack.add(sky)
        self.assertEqual(len(stack), 1)
        self.assertTrue(stack._is_active)
        stack.remove(sky)
        self.assertEqual(len(stack), 0)
        stack.add(sky)
        stack.clear()
        self.assertEqual(len(stack), 0)

    def test_set_fly_replaces(self):
        stack = BackgroundStack()
        stack.add(Clouds())
        stack.set_fly(Tunnel())
        items = list(stack)
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], Tunnel)
        stack.set_fly(None)
        self.assertEqual(len(stack), 0)

    def test_render_empty_draws_base_only(self):
        stack = BackgroundStack()
        # No extras — base always draws; needs a real surface
        import skia
        info = skia.ImageInfo.Make(32, 32, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        stack._render(
            surf.getCanvas(),
            32,
            32,
            0.0,
            CameraSample(16, 16, 1.0, 0.0, rest_x=16.0, rest_y=16.0),
            design_width=32,
            design_height=32,
        )
        self.assertEqual(len(stack), 0)

    def test_field_parallax_uv_uses_instance_knobs(self):
        class _Stub(BackgroundField):
            def draw(self, *args, **kwargs):
                pass

        b = _Stub()
        b.pan_response = 0.5
        b.zoom_response = 0.25
        cam = CameraSample(600, 500, 2.0, 0.0, rest_x=500.0, rest_y=400.0)
        ox, oy, scale, _ = b._parallax_uv(
            cam=cam,
            design_width=1000,
            design_height=800,
            fb_width=2000,
            fb_height=1600,
        )
        self.assertAlmostEqual(ox, -200.0)
        self.assertAlmostEqual(oy, 200.0)
        self.assertAlmostEqual(scale, 1.25)


class TestBackgroundScroll(_UnplacedTest):
    def _stub(self):
        class _Stub(BackgroundField):
            def draw(self, *args, **kwargs):
                pass

        return _Stub()

    def test_scroll_default_zero(self):
        b = self._stub()
        self.assertEqual(b.scroll, (0.0, 0.0))

    def test_scroll_has_one_spelling(self):
        # ``scroll=(x, y)`` only: per-axis ``scroll_x`` / ``scroll_y`` were an
        # undocumented second spelling (Fences) and are gone.
        b = self._stub()
        for name in ("scroll_x", "scroll_y"):
            self.assertFalse(hasattr(type(b), name), name)

    def test_scroll_rejects_nonfinite(self):
        b = self._stub()
        with self.assertRaises(ValueError):
            b.scroll = (float("nan"), 0.0)
        self.assertEqual(b.scroll, (0.0, 0.0))
        with self.assertRaises(ValueError):
            b.scroll = (0.0, float("inf"))
        self.assertEqual(b.scroll, (0.0, 0.0))
        b.scroll = (10.0, 0.0)
        b._advance_scroll(0.0)
        b._advance_scroll(float("nan"))
        b._advance_scroll(1.0)
        self.assertAlmostEqual(b._scroll_accum[0], 10.0, places=5)

    def test_scroll_integrates_and_matches_pan_direction(self):
        """scroll content +X matches pan_by content right → positive FB offset."""
        b = self._stub()
        b.pan_response = 0.0
        b.scroll = (100.0, 0.0)  # 100 design units/sec
        b._advance_scroll(0.0)
        b._advance_scroll(1.0)  # +100 design X over 1s
        cam = CameraSample(500, 400, 1.0, 0.0, rest_x=500.0, rest_y=400.0)
        ox, oy, _, _ = b._parallax_uv(
            cam=cam,
            design_width=1000,
            design_height=800,
            fb_width=1000,
            fb_height=800,
        )
        self.assertAlmostEqual(ox, 100.0)
        self.assertAlmostEqual(oy, 0.0)

    def test_scroll_y_up_negates_on_fb(self):
        # +design Y (content up) → negative FB offset_y
        b = self._stub()
        b.pan_response = 0.0
        b.scroll = (0.0, 50.0)
        b._advance_scroll(0.0)
        b._advance_scroll(1.0)
        cam = CameraSample(500, 400, 1.0, 0.0, rest_x=500.0, rest_y=400.0)
        ox, oy, _, _ = b._parallax_uv(
            cam=cam,
            design_width=1000,
            design_height=800,
            fb_width=1000,
            fb_height=800,
        )
        self.assertAlmostEqual(ox, 0.0)
        self.assertAlmostEqual(oy, -50.0)

    def test_scroll_independent_of_pan_response(self):
        b = self._stub()
        b.pan_response = 0.0
        b.scroll = (0.0, -80.0)  # invaders-style: roll down
        # Scroll counts from the field's birth (review 2026-10-09 W-T8): one
        # second after it → -80 design Y → +80 FB y.
        t0 = float(b._scroll_last_t or 0.0)
        b._advance_scroll(t0 + 1.0)
        cam = CameraSample(0.0, 0.0, 1.0, 0.0, rest_x=0.0, rest_y=0.0)
        ox, oy, _, _ = b._parallax_uv(
            cam=cam,
            design_width=1400,
            design_height=900,
            fb_width=1400,
            fb_height=900,
        )
        self.assertAlmostEqual(ox, 0.0)
        self.assertAlmostEqual(oy, 80.0)

    def test_reset_scroll_clears_accum(self):
        b = self._stub()
        b.scroll = (10.0, 0.0)
        b._advance_scroll(0.0)
        b._advance_scroll(2.0)
        b._reset_scroll()
        cam = CameraSample(500, 400, 1.0, 0.0, rest_x=500.0, rest_y=400.0)
        ox, oy, _, _ = b._parallax_uv(
            cam=cam,
            design_width=1000,
            design_height=800,
            fb_width=1000,
            fb_height=800,
        )
        self.assertAlmostEqual(ox, 0.0)
        self.assertAlmostEqual(oy, 0.0)
        # rate still set
        self.assertEqual(b.scroll, (10.0, 0.0))

    def test_scroll_constructor_arg(self):
        s = Stars(pan_response=0.0, scroll=(0.0, -45.0))
        self.assertEqual(s.scroll, (0.0, -45.0))
        d = Stardust(scroll=(10.0, -5.0))
        self.assertEqual(d.scroll, (10.0, -5.0))
        # live still works after construct
        s.scroll = (0.0, -60.0)
        self.assertEqual(s.scroll, (0.0, -60.0))

    def test_kinds_inherit_scroll(self):
        for cls in (
            Clouds, Plasma, Stars, Floor, Road, Ground,
            Debris, Embers, WindStreaks, Nebula, Lattice,
            ChurningClouds, FilamentField, Stardust, Chromadust, Nebuladust,
        ):
            with self.subTest(cls=cls.__name__):
                inst = cls()
                self.assertEqual(inst.scroll, (0.0, 0.0))
                inst.scroll = (0.0, -10.0)
                self.assertEqual(inst.scroll, (0.0, -10.0))


class TestBackgroundKindsDefaults(_UnplacedTest):
    def test_sky_gradient_defaults(self):
        s = SkyGradient()
        self.assertAlmostEqual(s.pan_response, 0.0)
        self.assertAlmostEqual(s.horizon, 0.0)
        self.assertEqual(len(s.top), 3)
        self.assertEqual(len(s.middle), 3)
        self.assertEqual(len(s.bottom), 3)
        custom = SkyGradient(bottom="navy")
        self.assertEqual(len(custom.bottom), 3)
        # horizon=0 → atmosphere (middle) at the bottom; no ground tint.
        full = SkyGradient("day", horizon=0.0)
        ramp0 = full._ramp_stops()
        self.assertEqual(len(ramp0), 2)
        self.assertAlmostEqual(ramp0[0][0], 0.0)
        self.assertEqual(ramp0[0][1], tuple(full.top))
        self.assertAlmostEqual(ramp0[-1][0], 1.0)
        self.assertEqual(ramp0[-1][1], tuple(full.middle))
        # horizon y-up 0.5 → middle sits on the mid-screen seam (same as Ground).
        half = SkyGradient("day", horizon=0.5)
        self.assertAlmostEqual(half.horizon, 0.5)
        self.assertAlmostEqual(half.fade, HORIZON_FADE)
        self.assertAlmostEqual(half._ramp_end_from_top(), 0.5)
        ramp = half._ramp_stops()
        self.assertAlmostEqual(ramp[0][0], 0.0)
        self.assertEqual(ramp[0][1], tuple(half.top))
        at_seam = [(p, c) for p, c in ramp if abs(p - 0.5) < 1e-6]
        self.assertTrue(at_seam)
        self.assertEqual(at_seam[0][1], tuple(half.middle))
        # Default fade: bottom colour ramps in just below the seam, not a hard cut.
        blend_at = 0.5 + HORIZON_FADE
        at_blend = [(p, c) for p, c in ramp if abs(p - blend_at) < 1e-6]
        self.assertTrue(at_blend)
        self.assertEqual(at_blend[0][1], tuple(half.bottom))
        self.assertAlmostEqual(ramp[-1][0], 1.0)
        self.assertEqual(ramp[-1][1], tuple(half.bottom))
        half._sync_gradient(900.0)
        self.assertIsNone(half._wallpaper.source.size)
        self.assertAlmostEqual(half._wallpaper.source._angle, 90.0)
        # fade=0 restores coincident mid/bottom stops (hard cut).
        crisp = SkyGradient("day", horizon=0.5, fade=0.0)
        crisp_ramp = crisp._ramp_stops()
        at_crisp = [(p, c) for p, c in crisp_ramp if abs(p - 0.5) < 1e-6]
        self.assertEqual(len(at_crisp), 2)
        self.assertEqual(at_crisp[0][1], tuple(crisp.middle))
        self.assertEqual(at_crisp[1][1], tuple(crisp.bottom))
        # horizon=1 → solid bottom (no sky).
        floor = SkyGradient("day", horizon=1.0)
        ramp1 = floor._ramp_stops()
        self.assertEqual(ramp1[0][1], tuple(floor.bottom))
        self.assertEqual(ramp1[-1][1], tuple(floor.bottom))
        # Low horizon (0.15) places atmosphere in the lower half, not mid-sky.
        low = SkyGradient("day", horizon=0.15)
        end = low._ramp_end_from_top()
        self.assertAlmostEqual(end, 0.85)
        at_low = [c for p, c in low._ramp_stops() if abs(p - end) < 1e-6]
        self.assertEqual(at_low[0], tuple(low.middle))
        # Fade longer than the remaining strip clamps to the bottom of the frame.
        tight = SkyGradient("day", horizon=0.02, fade=0.1)
        tr = tight._ramp_stops()
        self.assertAlmostEqual(tr[-1][0], 1.0)
        self.assertEqual(tr[-1][1], tuple(tight.bottom))
        self.assertEqual(sum(1 for p, _ in tr if abs(p - 1.0) < 1e-6), 1)

    def test_sky_clouds(self):
        self.assertAlmostEqual(Clouds().pan_response, 0.08)
        self.assertAlmostEqual(Clouds().res_scale, 0.5)

    def test_plasma_defaults(self):
        p = Plasma()
        self.assertAlmostEqual(p.pan_response, 0.3)
        self.assertAlmostEqual(p.zoom_response, 0.4)
        self.assertAlmostEqual(p.speed, 0.0)

    def test_borealis_defaults(self):
        a = Borealis()
        self.assertAlmostEqual(a.pan_response, 0.1)
        self.assertAlmostEqual(a.zoom_response, 0.15)
        self.assertAlmostEqual(a.height, 0.65)
        self.assertAlmostEqual(Borealis(height=0.4).height, 0.4)

    def test_mist_defaults(self):
        m = Mist()
        self.assertAlmostEqual(m.pan_response, 0.2)
        self.assertAlmostEqual(m.band, 0.4)

    def test_stars_defaults(self):
        s = Stars()
        self.assertAlmostEqual(s.pan_response, 0.02)
        self.assertAlmostEqual(s.zoom_response, 0.0)
        self.assertAlmostEqual(s.twinkle, 0.0)
        self.assertAlmostEqual(s.density, 0.8)

    def test_stardust_defaults(self):
        d = Stardust()
        self.assertAlmostEqual(d.pan_response, 0.08)
        self.assertAlmostEqual(d.zoom_response, 0.1)
        self.assertAlmostEqual(d.speed, 0.2)
        self.assertEqual(len(d.color2), 3)
        self.assertAlmostEqual(d.res_scale, 0.6)

    def test_stardust_builder_identity(self):
        from scena.fx_quality import activate_quality
        from scena import background_kinds as bk
        from scena._sksl_ambient import (
            stardust_builder,
            stardust_survival_builder,
        )

        captured = []
        orig = bk._draw_lowres

        def spy(field, canvas, w, h, builder, fw, *, res_scale, bind):
            captured.append(builder)

        bk._draw_lowres = spy
        cam = CameraSample(32, 32, 1.0, 0.0, rest_x=32.0, rest_y=32.0)
        try:
            activate_quality("high")
            captured.clear()
            Stardust().draw(None, 64, 64, 0.0, cam, design_width=64, design_height=64)
            self.assertIs(captured[-1], stardust_builder)
            activate_quality("low")
            captured.clear()
            Stardust().draw(None, 64, 64, 0.0, cam, design_width=64, design_height=64)
            self.assertIs(captured[-1], stardust_survival_builder)
        finally:
            bk._draw_lowres = orig
            activate_quality("high")

    def test_chromadust_defaults(self):
        from scena import Gradient
        c = Chromadust()
        self.assertTrue(c.rainbow)
        self.assertTrue(c.reflect)
        self.assertAlmostEqual(c.hue_speed, 0.25)
        self.assertAlmostEqual(c.saturation, 1.0)
        self.assertAlmostEqual(c.speed, 0.2)
        self.assertEqual(len(c.palette), 5)
        p = Chromadust("plasma")
        self.assertFalse(p.rainbow)
        g = Chromadust(Gradient("sunset"))
        self.assertFalse(g.rainbow)
        seq = Chromadust(("magenta", "cyan", "gold"))
        self.assertFalse(seq.rainbow)
        self.assertFalse(Chromadust(reflect=False).reflect)
        with self.assertRaises(ValueError):
            Chromadust("not-a-preset")

    def test_chromadust_builder_identity(self):
        from scena.fx_quality import activate_quality
        from scena import background_kinds as bk
        from scena._sksl_ambient import (
            chromadust_builder,
            chromadust_survival_builder,
        )

        captured = []
        orig = bk._draw_lowres

        def spy(field, canvas, w, h, builder, fw, *, res_scale, bind):
            captured.append(builder)

        bk._draw_lowres = spy
        cam = CameraSample(32, 32, 1.0, 0.0, rest_x=32.0, rest_y=32.0)
        try:
            activate_quality("high")
            captured.clear()
            Chromadust().draw(None, 64, 64, 0.0, cam, design_width=64, design_height=64)
            self.assertIs(captured[-1], chromadust_builder)
            captured.clear()
            Chromadust("plasma").draw(
                None, 64, 64, 0.0, cam, design_width=64, design_height=64,
            )
            self.assertIs(captured[-1], chromadust_builder)
            activate_quality("low")
            captured.clear()
            Chromadust().draw(None, 64, 64, 0.0, cam, design_width=64, design_height=64)
            self.assertIs(captured[-1], chromadust_survival_builder)
        finally:
            bk._draw_lowres = orig
            activate_quality("high")

    def test_nebuladust_defaults(self):
        n = Nebuladust()
        self.assertAlmostEqual(n.pan_response, 0.08)
        self.assertAlmostEqual(n.zoom_response, 0.1)
        self.assertAlmostEqual(n.speed, 0.2)
        self.assertEqual(len(n.color), 3)
        self.assertEqual(len(n.color2), 3)
        self.assertEqual(len(n.color3), 3)
        self.assertAlmostEqual(n.res_scale, 0.6)

    def test_nebuladust_builder_identity(self):
        from scena.fx_quality import activate_quality
        from scena import background_kinds as bk
        from scena._sksl_ambient import (
            nebuladust_builder,
            nebuladust_survival_builder,
        )

        captured = []
        orig = bk._draw_lowres

        def spy(field, canvas, w, h, builder, fw, *, res_scale, bind):
            captured.append(builder)

        bk._draw_lowres = spy
        cam = CameraSample(32, 32, 1.0, 0.0, rest_x=32.0, rest_y=32.0)
        try:
            activate_quality("high")
            captured.clear()
            Nebuladust().draw(None, 64, 64, 0.0, cam, design_width=64, design_height=64)
            self.assertIs(captured[-1], nebuladust_builder)
            activate_quality("low")
            captured.clear()
            Nebuladust().draw(None, 64, 64, 0.0, cam, design_width=64, design_height=64)
            self.assertIs(captured[-1], nebuladust_survival_builder)
        finally:
            bk._draw_lowres = orig
            activate_quality("high")

    def test_churningclouds_defaults(self):
        c = ChurningClouds()
        self.assertAlmostEqual(c.pan_response, 0.06)
        self.assertAlmostEqual(c.zoom_response, 0.08)
        self.assertAlmostEqual(c.speed, 0.4)
        self.assertAlmostEqual(c.alpha, 0.6)
        self.assertAlmostEqual(c.res_scale, 0.4)
        self.assertEqual(len(c.color), 3)
        self.assertEqual(len(c.color2), 3)
        c.res_scale = 0.25
        self.assertAlmostEqual(c.res_scale, 0.25)

    def test_filamentfield_defaults(self):
        f = FilamentField()
        self.assertAlmostEqual(f.pan_response, 0.18)
        self.assertAlmostEqual(f.zoom_response, 0.08)
        self.assertAlmostEqual(f.speed, 0.35)
        self.assertAlmostEqual(f.alpha, 0.55)
        self.assertAlmostEqual(f.res_scale, 0.5)
        self.assertEqual(len(f.color), 3)
        f.contrast = 1.5
        self.assertAlmostEqual(f.contrast, 1.5)

    def test_floor_defaults(self):
        f = Floor()
        self.assertAlmostEqual(f.pan_response, 0.0)
        self.assertAlmostEqual(f.grid, 0.75)
        self.assertEqual(len(f.sky), 3)

    def test_lattice_defaults(self):
        g = Lattice()
        self.assertEqual(g.fold, "hex")
        self.assertEqual(g.edge, "outline")
        self.assertAlmostEqual(g.pan_response, 0.25)
        self.assertAlmostEqual(g.spacing, 1.0)
        self.assertAlmostEqual(g.line, 1.0)
        self.assertAlmostEqual(g.alpha, 0.55)
        self.assertEqual(g.layers, 1)
        self.assertAlmostEqual(g.angle, 0.0)
        self.assertAlmostEqual(g.size, 1.0)
        self.assertAlmostEqual(g.layer_scale, 1.0)
        self.assertAlmostEqual(g.zoom_response, 0.35)


    def test_lattice_validation_and_recipe(self):
        with self.assertRaises(ValueError):
            Lattice(fold="hax")
        with self.assertRaises(ValueError):
            Lattice(edge="glow")
        with self.assertRaises(ValueError):
            Lattice(edge="nodes")
        c = Lattice(color="red")
        self.assertEqual(len(c.color), 3)
        r = Lattice(fold="tri", edge="fill", angle=10, size=0.4, layer_scale=1.5)
        self.assertEqual(r.fold, "tri")
        self.assertEqual(r.edge, "fill")
        self.assertAlmostEqual(r.angle, 10.0)
        self.assertAlmostEqual(r.size, 0.4)
        self.assertAlmostEqual(r.layer_scale, 1.5)
        with self.assertRaises(ValueError):
            Lattice(fold="grid")
        with self.assertRaises(ValueError):
            Lattice(fold="diamond")
        # live mutation — size capped at 1.7; layer_scale capped 1..2
        L = Lattice()
        L.fold = "tri"
        L.edge = "fill"
        L.layers = 0
        L.size = 2.5
        L.layer_scale = 0.5
        self.assertEqual(L.fold, "tri")
        self.assertEqual(L.edge, "fill")
        self.assertEqual(L.layers, 1)
        self.assertAlmostEqual(L.size, 1.7)
        self.assertAlmostEqual(L.layer_scale, 1.0)
        L.layer_scale = 3.0
        self.assertAlmostEqual(L.layer_scale, 2.0)
        L.size = 0.01
        self.assertAlmostEqual(L.size, 0.05)

    def test_ambient_arcade_defaults(self):
        self.assertAlmostEqual(Debris().density, 0.7)
        self.assertAlmostEqual(Embers().rise, 0.8)
        w = WindStreaks()
        self.assertAlmostEqual(w.pan_response, 0.85)
        self.assertAlmostEqual(w.glow, 0.9)
        self.assertAlmostEqual(w.angle, 0.0)
        self.assertAlmostEqual(Ground().horizon, 0.42)
        self.assertAlmostEqual(Ground().fade, HORIZON_FADE)
        self.assertAlmostEqual(Ground().detail, 0.0)
        g_blue = Ground(color="blue")
        self.assertGreater(g_blue.edge[2], g_blue.edge[0])  # bluish auto horizon
        self.assertAlmostEqual(g_blue.color[2], 1.0, places=4)
        self.assertAlmostEqual(Nebula().alpha, 0.55)
        self.assertEqual(Lattice(fold="square").fold, "square")
        self.assertEqual(Lattice(fold="tri", edge="fill").edge, "fill")
        self.assertEqual(Lattice(layers=9).layers, 3)

    def test_road_defaults_horizontal(self):
        r = Road()
        self.assertAlmostEqual(r.pan_response, 0.85)
        self.assertAlmostEqual(r.speed, 1.0)
        self.assertEqual(len(r.sky), 3)

    def test_startunnel_defaults(self):
        t = Tunnel()
        self.assertAlmostEqual(t.pan_response, 0.0)
        self.assertAlmostEqual(t.speed, 1.0)
        self.assertAlmostEqual(t.density, 1.0)
        self.assertIsNone(t.center)

    def test_starfield_defaults(self):
        s = StarFly()
        self.assertAlmostEqual(s.pan_response, 0.0)
        self.assertAlmostEqual(s.speed, 1.0)
        self.assertAlmostEqual(s.density, 1.0)
        self.assertIsNone(s.center)

    def test_fly_center_stored_and_mutable(self):
        t = Tunnel(center=(200.0, -40.0))
        self.assertEqual(t.center, (200.0, -40.0))
        t.center = (0.0, 80.0)
        self.assertEqual(t.center, (0.0, 80.0))
        t.center = None
        self.assertIsNone(t.center)
        s = StarFly(center=(50.0, 10.0))
        self.assertEqual(s.center, (50.0, 10.0))

    def test_radial_fly_uv_center_plus_opt_in_pan(self):
        """center= is framing; pan_response banks it. Default pan adds nothing."""
        cam_rest = CameraSample(
            pan_x=0.0, pan_y=0.0, zoom=1.0, rotation=0.0,
            rest_x=0.0, rest_y=0.0,
        )
        cam_look = CameraSample(
            pan_x=100.0, pan_y=0.0, zoom=1.0, rotation=0.0,
            rest_x=0.0, rest_y=0.0,
        )
        t = Tunnel(center=(200.0, 0.0), pan_response=0.0)
        ox, oy, _, _ = _radial_fly_uv(
            t, cam=cam_look,
            design_width=1400.0, design_height=900.0,
            fb_width=1400.0, fb_height=900.0,
        )
        self.assertAlmostEqual(ox, 200.0)
        self.assertAlmostEqual(oy, 0.0)
        t.pan_response = 1.0
        ox, oy, _, _ = _radial_fly_uv(
            t, cam=cam_look,
            design_width=1400.0, design_height=900.0,
            fb_width=1400.0, fb_height=900.0,
        )
        # look +100 → pan offset −100; plus authored +200
        self.assertAlmostEqual(ox, 100.0)
        self.assertAlmostEqual(oy, 0.0)
        n = Tunnel(pan_response=0.0)
        ox, oy, _, _ = _radial_fly_uv(
            n, cam=cam_rest,
            design_width=1400.0, design_height=900.0,
            fb_width=1400.0, fb_height=900.0,
        )
        self.assertAlmostEqual(ox, 0.0)
        self.assertAlmostEqual(oy, 0.0)

    def test_planetfly_defaults_into(self):
        p = PlanetFly()
        self.assertAlmostEqual(p.pan_response, 0.0)
        self.assertAlmostEqual(p.speed, 1.0)
        self.assertAlmostEqual(p.relief, 0.9)
        self.assertAlmostEqual(p.size, 0.55)
        self.assertAlmostEqual(p.bright, 1.15)
        self.assertEqual(p.roll, "into")
        self.assertTrue(p._roll_into())
        self.assertEqual(len(p.space), 3)

    def test_planetfly_side_roll(self):
        p = PlanetFly(roll="side")
        self.assertFalse(p._roll_into())
        p.roll = "into"
        self.assertTrue(p._roll_into())

    def test_color_name_resolves(self):
        p = Plasma(color="magenta")
        self.assertTrue(all(0.0 <= c <= 1.0 for c in p.color))
        self.assertTrue(all(0.0 <= c <= 1.0 for c in Stars(color="gold").color))

    def test_knobs_mutable_after_construct(self):
        s = Stars()
        s.density = 1.2
        s.pan_response = 0.1
        self.assertAlmostEqual(s.density, 1.2)
        g = Lattice()
        g.spacing = 1.5
        g.scroll = (30.0, 0.0)
        self.assertAlmostEqual(g.spacing, 1.5)
        self.assertEqual(g.scroll, (30.0, 0.0))

    def test_kinds_exportable_from_scena(self):
        from scena import (
            Stars as ScenaStars, Stardust as ScenaStardust,
            Chromadust as ScenaChromadust, Nebuladust as ScenaNebuladust,
            Plasma as ScenaPlasma, Borealis as ScenaBorealis,
            Floor as F2,
            Lattice as L2, Road as R2,
            Tunnel as ST2, StarFly as SF2, PlanetFly as PF2,
            SkyGradient, Clouds, Mist, Wallpaper,
            Debris, Embers, WindStreaks, Ground, Nebula, Lattice,
            ChurningClouds as ScenaChurningClouds,
            FilamentField as ScenaFilamentField,
        )
        from scena import background_kinds as bf
        self.assertIs(ScenaStars, bf.Stars)
        self.assertIs(ScenaStardust, bf.Stardust)
        self.assertIs(ScenaChromadust, bf.Chromadust)
        self.assertIs(ScenaNebuladust, bf.Nebuladust)
        self.assertFalse(hasattr(bf, "Stardust2"))
        self.assertIs(ScenaPlasma, bf.Plasma)
        self.assertIs(ScenaBorealis, bf.Borealis)
        self.assertIs(ScenaChurningClouds, bf.ChurningClouds)
        self.assertIs(ScenaFilamentField, bf.FilamentField)
        self.assertIs(Tunnel, ST2)
        self.assertIs(StarFly, SF2)
        self.assertIs(Lattice, L2)
        self.assertIs(Road, R2)
        self.assertIs(PlanetFly, PF2)
        self.assertTrue(callable(SkyGradient))
        self.assertTrue(callable(Wallpaper))
        self.assertTrue(callable(Clouds))
        self.assertTrue(callable(Mist))
        for cls in (
            Debris, Embers, WindStreaks, Ground, Nebula, Lattice,
            ChurningClouds, FilamentField,
        ):
            self.assertTrue(callable(cls))
        s = ScenaStars()
        self.assertAlmostEqual(s.pan_response, 0.02)
        self.assertAlmostEqual(s.density, 0.8)
        sg = SkyGradient("sunset")
        self.assertEqual(len(sg.top), 3)
        from scena.style import GradientType
        self.assertAlmostEqual(sg._wallpaper.source._angle, 90.0)
        self.assertEqual(sg._wallpaper.source._type, GradientType.LINEAR)
        from scena.gradient_presets import get_preset, sample_stops_rgb
        z, h, btm = sample_stops_rgb(get_preset("sunset"))
        self.assertEqual(sg.top, z)
        self.assertEqual(sg.middle, h)
        self.assertEqual(sg.bottom, btm)
        ocean_sky = SkyGradient("ocean")
        oz, _, _ = sample_stops_rgb(get_preset("ocean"))
        self.assertEqual(ocean_sky.top, oz)
        self.assertIsNotNone(sky_palette("day"))
        self.assertAlmostEqual(ScenaChurningClouds().res_scale, 0.4)
        self.assertAlmostEqual(ScenaFilamentField().res_scale, 0.5)

class TestCanvasFacade(unittest.TestCase):
    def setUp(self):
        from scena import canvas, init
        init(width=800, height=600)
        canvas.background.clear()
        canvas.background.reset_base()

    def test_canvas_background_and_set_fly(self):
        from scena import canvas

        canvas.background.clear()
        self.assertFalse(canvas.background._is_active)
        canvas.background.add(Clouds())
        self.assertTrue(canvas.background._is_active)
        canvas.set_fly(Tunnel())
        self.assertEqual(len(canvas.background), 1)
        self.assertIsInstance(list(canvas.background)[0], Tunnel)
        canvas.set_fly(None)
        self.assertEqual(len(canvas.background), 0)

    def test_set_origin_updates_background_rest(self):
        from scena import canvas

        canvas.reset_view()
        self.assertAlmostEqual(canvas.pan_rest_x, canvas.width * 0.5)
        self.assertAlmostEqual(canvas.pan_rest_y, canvas.height * 0.5)
        canvas.set_origin("center")
        self.assertAlmostEqual(canvas.pan_x, 0.0)
        self.assertAlmostEqual(canvas.pan_y, 0.0)
        self.assertAlmostEqual(canvas.pan_rest_x, 0.0)
        self.assertAlmostEqual(canvas.pan_rest_y, 0.0)
        # leave at corner so other tests/suites start neutral
        canvas.reset_view()



class TestWallpaperAndBase(_UnplacedTest):
    def test_default_base_is_black_wallpaper(self):
        stack = BackgroundStack()
        self.assertIsInstance(stack.base, Wallpaper)
        from scena.color import Color
        self.assertIsInstance(stack.base.source, Color)

    def test_clear_preserves_base(self):
        stack = BackgroundStack()
        from scena.color import Color
        stack.base = Color(0.2, 0.3, 0.4)
        stack.add(Clouds())
        stack.clear()
        self.assertEqual(len(stack), 0)
        self.assertIsInstance(stack.base, Wallpaper)
        self.assertAlmostEqual(stack.base.source._r, 0.2, places=5)

    def test_reset_base(self):
        stack = BackgroundStack()
        from scena.color import Color
        stack.base = Color(1, 0, 0)
        stack.reset_base()
        self.assertIsInstance(stack.base, Wallpaper)
        self.assertAlmostEqual(stack.base.source._r, 0.0, places=5)

    def test_wrap_paint_on_add(self):
        stack = BackgroundStack()
        from scena.color import Color
        f = stack.add(Color(0.5, 0.5, 0.5))
        self.assertIsInstance(f, Wallpaper)
        self.assertEqual(len(stack), 1)

    def test_wallpaper_solid_fast_path_no_shader_cache(self):
        from scena.color import Color
        w = Wallpaper(Color(0.1, 0.1, 0.1))
        # Drawing solid should not populate shader paint.
        import skia
        info = skia.ImageInfo.Make(64, 64, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        cam = CameraSample(32, 32, 1.0, 0.0, rest_x=32.0, rest_y=32.0)
        w.draw(surf.getCanvas(), 64, 64, 0.0, cam, design_width=64, design_height=64)
        self.assertIsNone(w._base_fill)

    def test_wallpaper_accepts_pan_response_on_solid(self):
        from scena.color import Color
        w = Wallpaper(Color(0, 0, 0), pan_response=0.5, zoom_response=0.3)
        self.assertAlmostEqual(w.pan_response, 0.5)
        self.assertAlmostEqual(w.zoom_response, 0.3)

    def test_rotated_sky_covers_viewport_corners(self):
        """Camera rotation must not leave previous-frame pixels in the corners.

        SkyGradient paints via Wallpaper CTM. A viewport-sized rect rotated
        about center does not cover the FB; the draw path must expand (and
        clear) so every device pixel is written.
        """
        import skia
        w, h = 64, 48
        info = skia.ImageInfo.Make(
            w, h, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType,
        )
        surf = skia.Surface.MakeRaster(info)
        canvas = surf.getCanvas()
        canvas.clear(skia.Color4f(1.0, 0.0, 1.0, 1.0))  # magenta sentinel
        sky = SkyGradient("light blue", rotation_response=1.0)
        cam = CameraSample(
            pan_x=32.0, pan_y=24.0, zoom=1.0, rotation=35.0,
            rest_x=32.0, rest_y=24.0,
        )
        sky.draw(canvas, float(w), float(h), 0.0, cam, design_width=64, design_height=48)
        img = surf.makeImageSnapshot()
        buf = bytearray(w * h * 4)
        self.assertTrue(img.readPixels(info, buf, w * 4, 0, 0))

        def pixel(x, y):
            i = (y * w + x) * 4
            return buf[i], buf[i + 1], buf[i + 2], buf[i + 3]

        for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            r, g, b, a = pixel(x, y)
            self.assertFalse(
                r > 200 and b > 200 and g < 40,
                f"corner ({x},{y}) still magenta sentinel: {(r, g, b, a)}",
            )
            self.assertGreater(a, 200, f"corner ({x},{y}) not opaque: {(r, g, b, a)}")


class TestCanvasBackgroundBase(unittest.TestCase):
    def setUp(self):
        from scena import canvas, init
        init(width=800, height=600)
        canvas.background.clear()
        canvas.background.reset_base()

    def test_background_assign_sets_base_source(self):
        from scena import canvas
        canvas.background = (0.1, 0.2, 0.3)
        self.assertIsInstance(canvas.background.base, Wallpaper)
        self.assertAlmostEqual(canvas.background.base.source._r, 0.1, places=5)

    def test_background_base_assign(self):
        from scena import canvas
        from scena.color import Color
        c = Color(0.4, 0.5, 0.6)
        canvas.background.base = c
        self.assertIs(canvas.background.base.source, c)

    def test_wallpaper_camera_kwargs(self):
        from scena import canvas
        from scena.color import Color
        canvas.background = Wallpaper(Color(0.0, 0.0, 0.0), pan_response=0.2, scroll=(1.0, 0.0))
        self.assertAlmostEqual(canvas.background.base.pan_response, 0.2)
        self.assertEqual(canvas.background.base.scroll, (1.0, 0.0))

    def test_wallpaper_image_file_assigns_and_places(self):
        from scena import canvas
        from scena.style import BackgroundImage
        import skia
        info = skia.ImageInfo.Make(8, 8, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        img = surf.makeImageSnapshot()
        w = Wallpaper(img, fit="contain", pan_response=0.15)
        self.assertIs(canvas.background.base, w)
        self.assertIsInstance(w.source, BackgroundImage)
        self.assertEqual(w.source.fit, "contain")
        self.assertAlmostEqual(w.pan_response, 0.15)
        canvas.background = Wallpaper(image=img, fit="cover")
        self.assertIsInstance(canvas.background.base, Wallpaper)
        self.assertIsInstance(canvas.background.base.source, BackgroundImage)
        self.assertEqual(canvas.background.base.source.fit, "cover")

    def test_assign_filename_string_wraps_image(self):
        import warnings
        from scena import canvas
        from scena.style import BackgroundImage
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            canvas.background = "plate.jpg"
        self.assertIsInstance(canvas.background.base, Wallpaper)
        self.assertIsInstance(canvas.background.base.source, BackgroundImage)

    def test_clear_and_reset_api(self):
        from scena import canvas
        from scena.color import Color
        canvas.background.base = Color(0.3, 0.3, 0.3)
        canvas.background.add(Clouds())
        canvas.background.clear()
        self.assertEqual(len(canvas.background), 0)
        self.assertAlmostEqual(canvas.background.base.source._r, 0.3, places=5)
        canvas.background.reset_base()
        self.assertAlmostEqual(canvas.background.base.source._r, 0.0, places=5)

    def test_background_rejects_look(self):
        from scena import canvas, Neon
        with self.assertRaises(TypeError):
            canvas.background = Neon()


class TestEmbersDefaultIsVisible(unittest.TestCase):
    """``Embers()`` on a dark base must read as embers.

    Regression 2026-10: at density 0.7 / alpha 0.7 most embers took the dark
    end of the ramp (color × (0.4, 0.15, 0.05)) as 1–2 px cores: 0.03 % of the
    frame lit, max channel step 48 — an empty-looking sky. Defaults are now
    density 1.1 / alpha 0.95, the dim end glows the ember color, and every
    ember has a soft halo.
    """

    def test_defaults_light_the_sky(self):
        import os
        import sys
        import numpy as np
        import skia
        import scena
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from system_support import system_world

        def screen(w):
            a = np.asarray(w.surface.makeImageSnapshot().toarray(
                colorType=skia.kRGBA_8888_ColorType))
            return a[: int(scena.canvas.height), : int(scena.canvas.width), :3].astype(int)

        with system_world(draw=True) as w:
            scena.canvas.background = "#12141a"
            w.step(1)
            base = screen(w)
            scena.canvas.background.add(scena.Embers())
            w.step(30, draw=False)
            w.step(1)
            d = np.abs(screen(w) - base).max(axis=2)
        self.assertGreater(float((d >= 24).mean()), 0.008)    # ≥ 0.8 % of the frame lit
        self.assertGreater(int(d.max()), 120)                 # bright cores, not dark red


class TestCloudsHaveNoGridEdges(unittest.TestCase):
    """``Clouds`` must not draw straight lattice-aligned edges.

    Regression 2026-10: every fbm octave sat on the same axes, so value
    noise's axis ridges added up and smoothstep() cut a straight vertical
    cloud edge and a square hole (visible in the Guia's Clouds card). Each
    octave now turns its domain. Measure: the longest run of rows in one
    column where the alpha jumps sideways (a straight vertical edge). The
    aligned shader reached 74–80 rows at 960×600; the rotated one ~51–54.
    """

    def test_no_long_straight_vertical_edge(self):
        import numpy as np
        import skia
        import scena
        from scena.background import CameraSample

        w, h = 960, 600
        cam = CameraSample(pan_x=500.0, pan_y=312.5, zoom=1.0, rotation=0.0,
                           rest_x=500.0, rest_y=312.5)

        def longest_edge(t):
            surf = skia.Surface(w, h)
            c = surf.getCanvas()
            c.clear(skia.Color(0, 0, 0, 0))
            scena.Clouds(res_scale=1.0).draw(c, w, h, t, cam, design_width=1000,
                                             design_height=625, fw=None)
            a = np.asarray(surf.makeImageSnapshot().toarray(
                colorType=skia.kRGBA_8888_ColorType))[..., 3].astype(int)
            strong = np.abs(np.diff(a, axis=1)) >= 3
            best = 0
            for col in strong.T:
                # Longest run of consecutive True values in this column.
                padded = np.concatenate(([0], col.astype(int), [0]))
                edges = np.flatnonzero(np.diff(padded))
                if edges.size:
                    best = max(best, int((edges[1::2] - edges[::2]).max()))
            return best

        for t in (0.0, 3.0, 7.0, 13.0, 21.0):
            with self.subTest(t=t):
                self.assertLess(longest_edge(t), 64)


if __name__ == "__main__":
    unittest.main()
