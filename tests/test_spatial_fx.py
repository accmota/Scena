"""Unit tests for registered SpatialFx emitters."""
from __future__ import annotations

import unittest

from scena import init, canvas
from scena.shapes import Circle, Rect, Line
from scena.state import Attribute
from scena import spatial_fx as sfx
from scena.spatial_fx import (
    Fire,
    Rain,
    Jet,
    Sparks,
    GlowSpot,
    Orb,
    Sunburst,
    Starburst,
    Warp,
    Portal,
    PadModel,
    BeamModel,
    tick_all_spatial_fx,
    registered_count,
)


class SpatialFxTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=800, height=600)

    def setUp(self):
        self.t = 100.0
        sfx.set_now_fn(lambda: self.t)
        # hard-destroy any leftover emitters
        for fx in list(sfx._active_fx):
            try:
                fx.destroy()
            except Exception:
                sfx.unregister_spatial(fx)

    def tearDown(self):
        for fx in list(sfx._active_fx):
            try:
                fx.destroy()
            except Exception:
                sfx.unregister_spatial(fx)
        sfx.set_now_fn(None)

    def advance(self, dt: float = 1.0 / 60.0) -> None:
        self.t += float(dt)
        tick_all_spatial_fx(self.t)


class TestRegistration(SpatialFxTestBase):
    def test_construct_registers_on_layer(self):
        c = Fire(center=(200, 150))
        self.assertEqual(c.layer, "default")
        self.assertTrue(c.visible)
        self.assertTrue(c.is_alive)
        self.assertIn(c, canvas._engine.registry.layers["default"]._objects)
        self.assertTrue(canvas._engine.registry.is_live(c))

    def test_soft_remove_keeps_alive(self):
        c = Fire(center=(10, 10))
        c.undraw()
        self.assertTrue(c.is_alive)
        self.assertIsNone(c.layer)
        self.assertNotIn(c, canvas._engine.registry.layers["default"]._objects)
        # still registered for tick
        self.assertIn(c, sfx._active_fx)

    def test_destroy_hard(self):
        c = Fire(center=(10, 10))
        c.destroy()
        self.assertFalse(c.is_alive)
        self.assertFalse(canvas._engine.registry.is_live(c))
        self.assertNotIn(c, sfx._active_fx)


class TestDomainModels(SpatialFxTestBase):
    def test_rain_corner_corner(self):
        r = Rain(p1=(0, 0), p2=(200, 100))
        self.assertEqual(r.model, PadModel.CORNER_CORNER)
        aabb = r._domain_aabb()
        self.assertAlmostEqual(aabb[0], 0.0)
        self.assertAlmostEqual(aabb[2], 200.0)
        self.assertAlmostEqual(aabb[3], 100.0)

    def test_rain_center_wh(self):
        r = Rain(center=(100, 50), width=80, height=40)
        self.assertEqual(r.model, PadModel.CENTER_WH)
        aabb = r._domain_aabb()
        self.assertAlmostEqual(aabb[0], 60.0)
        self.assertAlmostEqual(aabb[1], 30.0)
        self.assertAlmostEqual(aabb[2], 140.0)
        self.assertAlmostEqual(aabb[3], 70.0)

    def test_rain_aabb_grows_with_size(self):
        small = Rain(center=(0, 0), width=50, height=50)
        big = Rain(center=(0, 0), width=200, height=50)
        self.assertGreater(big._domain_aabb()[2] - big._domain_aabb()[0],
                         small._domain_aabb()[2] - small._domain_aabb()[0])

    def test_jet_point_point(self):
        j = Jet(p1=(0, 0), p2=(100, 0), width=10)
        self.assertEqual(j.model, BeamModel.POINT_POINT)
        x0, y0, x1, y1, length, w = j._beam_frame()
        self.assertAlmostEqual(length, 100.0)
        self.assertAlmostEqual(x1, 100.0)

    def test_jet_origin_angle_length(self):
        j = Jet(origin=(0, 0), angle=0, length=50, width=8)
        self.assertEqual(j.model, BeamModel.ORIGIN_ANGLE_LENGTH)
        x0, y0, x1, y1, length, w = j._beam_frame()
        self.assertAlmostEqual(length, 50.0)
        self.assertAlmostEqual(x1, 50.0)
        self.assertAlmostEqual(y1, 0.0)

    def test_campfire_radius_aabb(self):
        c = Fire(center=(50, 50), radius=25)
        aabb = c._domain_aabb()
        # soft irregular lobes use a pad > geometric radius
        self.assertLess(aabb[0], 25.0)
        self.assertGreater(aabb[2], 75.0)
        self.assertAlmostEqual(aabb[0] + aabb[2], 100.0, places=3)
        self.assertAlmostEqual(aabb[1] + aabb[3], 100.0, places=3)


class TestLinking(SpatialFxTestBase):
    def test_center_link_tracks_source(self):
        ship = Circle(center=(100, 200), radius=10)
        fire = Fire(center=lambda: ship.center, radius=30)
        self.assertAlmostEqual(float(fire.center.x), 100.0)
        self.assertAlmostEqual(float(fire.center.y), 200.0)
        ship.center._takein((300, 400))
        self.assertAlmostEqual(float(fire.center.x), 300.0)
        self.assertAlmostEqual(float(fire.center.y), 400.0)

    def test_plume_angle_default_and_set(self):
        p = Fire(style="plume", center=(10, 10), width=20, angle=0)
        self.assertAlmostEqual(float(p.angle), 0.0)
        p.angle = 45.0
        self.assertAlmostEqual(float(p.angle), 45.0)

    def test_directed_fire_width_length(self):
        p = Fire(style="plume", center=(10, 10), width=20)
        self.assertAlmostEqual(float(p.width), 20.0)
        self.assertAlmostEqual(float(p.length), 44.0)  # 2.2 × width
        self.assertEqual(
            p._defining_part_names, {"center", "width", "length", "angle"}
        )
        self.assertIsInstance(p.width, float)
        self.assertIsInstance(p.length, float)
        p["width"] @= Attribute(30.0)
        self.assertEqual(p.width, 30.0)
        p["width"].unlink()
        p.width = 16.0
        p.length = 50.0
        self.assertEqual(p.width, 16.0)
        self.assertEqual(p.length, 50.0)
        tongues = Fire(style="tongues", center=(0, 0), width=10)
        self.assertAlmostEqual(float(tongues.length), 26.0)
        embers = Fire(style="embers", center=(0, 0), width=10)
        self.assertAlmostEqual(float(embers.length), 24.0)
        with self.assertRaises(TypeError):
            Fire(style="plume", center=(0, 0), radius=20)

    def test_from_rect_links(self):
        rect = Rect(center=(200, 150), width=120, height=80)
        rain = Rain.from_rect(rect)
        self.assertEqual(rain.model, PadModel.CENTER_WH)
        self.assertAlmostEqual(float(rain.center.x), 200.0)
        rect.center._takein((10, 20))
        self.assertAlmostEqual(float(rain.center.x), 10.0)
        self.assertAlmostEqual(float(rain.center.y), 20.0)

    def test_from_line_links(self):
        line = Line(p1=(0, 0), p2=(40, 30))
        jet = Jet.from_line(line, width=12)
        self.assertEqual(jet.model, BeamModel.POINT_POINT)
        self.assertAlmostEqual(float(jet.p2.x), 40.0)
        line.p2._takein((80, 0))
        self.assertAlmostEqual(float(jet.p2.x), 80.0)

    def test_radius_is_bare_and_bracket_linkable(self):
        fire = Fire(center=(50, 50), radius=25)
        self.assertIsInstance(fire.radius, float)
        self.assertEqual(fire.radius, 25.0)
        fire["radius"] @= Attribute(40.0)
        self.assertTrue(fire["radius"].is_linked)
        self.assertEqual(fire.radius, 40.0)
        fire["radius"].unlink()
        fire.radius = 12.0
        self.assertEqual(fire.radius, 12.0)

    def test_jet_dual_model_defining_parts(self):
        j_pp = Jet(p1=(0, 0), p2=(100, 0), width=10)
        self.assertEqual(j_pp._defining_part_names, {"p1", "p2", "width"})
        self.assertIsInstance(j_pp.width, float)
        j_oal = Jet(origin=(0, 0), angle=30, length=50, width=8)
        self.assertEqual(
            j_oal._defining_part_names, {"origin", "angle", "length", "width"}
        )
        self.assertIsInstance(j_oal.angle, float)
        self.assertIsInstance(j_oal.length, float)
        self.assertEqual(j_oal.angle, 30.0)

    def test_rain_dual_model_defining_parts(self):
        r_cc = Rain(p1=(0, 0), p2=(100, 80))
        self.assertEqual(r_cc._defining_part_names, {"p1", "p2"})
        r_wh = Rain(center=(50, 50), width=40, height=30)
        self.assertEqual(
            r_wh._defining_part_names, {"center", "width", "height"}
        )
        self.assertIsInstance(r_wh.width, float)
        self.assertIsInstance(r_wh.height, float)


class TestTickVsDraw(SpatialFxTestBase):
    def test_tick_spawns_particles_without_draw(self):
        r = Rain(p1=(0, 0), p2=(400, 300), amount=1.0)
        self.assertEqual(r._bank.n, 0)
        for _ in range(40):
            self.advance()
        self.assertGreater(r._bank.n, 0)

    def test_jet_tick_spawn(self):
        j = Jet(p1=(0, 0), p2=(100, 0), width=16, amount=2.0)
        for _ in range(20):
            self.advance()
        self.assertGreater(j._bank.n, 0)

    def test_sparks_tick_spawn(self):
        s = Sparks(center=(100, 100), radius=40, rate=80)
        for _ in range(20):
            self.advance()
        self.assertGreater(s._bank.n, 0)

    def test_plume_soa_bank(self):
        p = Fire(style="plume", center=(10, 10), width=20)
        for _ in range(20):
            self.advance()
        self.assertTrue(hasattr(p, "_bank"))
        self.assertGreater(p._bank.n, 0)

    def test_registered_count(self):
        n0 = registered_count()
        Fire(center=(0, 0))
        Rain(p1=(0, 0), p2=(50, 50))
        self.assertEqual(registered_count(), n0 + 2)


class TestFireStyleFamily(SpatialFxTestBase):
    def test_style_dispatch_isinstance(self):
        camp = Fire(center=(0, 0))
        self.assertIsInstance(camp, Fire)
        self.assertEqual(type(camp).__name__, "Fire")
        for st in ("soft", "plume", "tongues", "embers", "blaze"):
            size = {"radius": 20} if st == "soft" else {"width": 20}
            fx = Fire(style=st, center=(10, 10), **size)
            self.assertIsInstance(fx, Fire)
            self.assertNotEqual(type(fx), Fire)

    def test_invalid_fire_style_raises(self):
        with self.assertRaises(ValueError):
            Fire(style="huge")

    def test_camp_amount_speed_live(self):
        camp = Fire(center=(10, 10), radius=20, amount=1.0, speed=1.2)
        self.assertAlmostEqual(camp._fill.amount, 1.0)
        self.assertAlmostEqual(camp._fill.speed, 1.2)
        camp.amount = 0.4
        camp.speed = 2.0
        camp._tick(1.0 / 60.0, 0.0)
        self.assertAlmostEqual(camp._fill.amount, 0.4)
        self.assertAlmostEqual(camp._fill.speed, 2.0)
        self.assertAlmostEqual(camp._fill._amount, 0.4)
        self.assertAlmostEqual(camp._fill._speed, 2.0)

    def test_sunburst_starburst_construct(self):
        sun = Sunburst(center=(10, 10), radius=20)
        star = Starburst(center=(20, 20), radius=18)
        self.assertTrue(sun.is_alive)
        self.assertTrue(star.is_alive)
        self.assertIsNone(sun.color)

    def test_sunburst_color_tint(self):
        import skia
        plain = Sunburst(center=(40, 40), radius=18)
        tinted = Sunburst(center=(40, 40), radius=18, color="cyan")
        self.assertEqual(tinted.color, (0.0, 1.0, 1.0))
        tinted.color = "gold"
        from scena.color import Color
        expected = tuple(float(c) for c in Color("gold").rgb[:3])
        self.assertEqual(tinted.color, expected)
        tinted.color = None
        self.assertIsNone(tinted.color)
        surf = skia.Surface.MakeRasterN32Premul(80, 80)
        canvas = surf.getCanvas()
        plain.draw(canvas)
        tinted.draw(canvas)
        Sunburst(center=(40, 40), radius=18, color="magenta").draw(canvas)

    def test_sunburst_default_palette_unchanged_vs_tint(self):
        """Omit color= uses the hardcoded star ramp; a tint must not match it."""
        import skia

        def pixels(fx):
            surf = skia.Surface.MakeRasterN32Premul(64, 64)
            canvas = surf.getCanvas()
            canvas.clear(skia.Color4f(0, 0, 0, 1))
            fx.draw(canvas)
            img = surf.makeImageSnapshot()
            return bytes(img.tobytes())

        a = Sunburst(center=(32, 32), radius=16)
        b = Sunburst(center=(32, 32), radius=16, color="cyan")
        pa = pixels(a)
        self.assertEqual(pa, pixels(a))
        self.assertNotEqual(pa, pixels(b))

    def test_tick_error_propagates(self):
        from scena.spatial_fx import PointDomainFx, tick_all_spatial_fx

        class BoomFx(PointDomainFx):
            def __init__(self):
                self._init_point_domain(center=(10, 10), radius=8)

            def _tick(self, dt, t):
                raise RuntimeError("tick boom")

        class OkFx(PointDomainFx):
            def __init__(self):
                self.n = 0
                self._init_point_domain(center=(20, 20), radius=8)

            def _tick(self, dt, t):
                self.n += 1

        boom = BoomFx()
        ok = OkFx()
        try:
            with self.assertRaisesRegex(RuntimeError, "tick boom"):
                tick_all_spatial_fx()
            boom.destroy()
            tick_all_spatial_fx()  # healthy emitters keep ticking
            self.assertGreaterEqual(ok.n, 1)
        finally:
            boom.destroy()
            ok.destroy()


class TestEffectColorResolve(SpatialFxTestBase):
    def test_jet_named_color(self):
        j = Jet(origin=(0, 0), angle=0, length=40, color="cyan")
        self.assertEqual(j.color, (0.0, 1.0, 1.0))

    def test_rain_color_object(self):
        from scena.color import Color
        r = Rain(p1=(0, 0), p2=(100, 100), color=Color("steel blue"))
        expected = tuple(float(c) for c in Color("steel blue").rgb[:3])
        self.assertEqual(r.color, expected)

    def test_sparks_named_color(self):
        s = Sparks(center=(10, 10), color="gold")
        from scena.color import Color
        expected = tuple(float(c) for c in Color("gold").rgb[:3])
        self.assertEqual(s.color, expected)

    def test_glowspot_named_color_and_radius(self):
        g = GlowSpot(center=(40, 50), radius=32, color="cyan")
        self.assertEqual(g.color, (0.0, 1.0, 1.0))
        self.assertAlmostEqual(float(g.radius), 32.0)
        self.assertAlmostEqual(float(g.center.x), 40.0)
        aabb = g._domain_aabb()
        self.assertLess(aabb[0], 40.0)
        self.assertGreater(aabb[2], 40.0)
        g.color = "gold"
        from scena.color import Color
        expected = tuple(float(c) for c in Color("gold").rgb[:3])
        self.assertEqual(g.color, expected)


class TestOrb(SpatialFxTestBase):
    def test_default_is_sun_like(self):
        orb = Orb(center=(40, 50), radius=32)
        self.assertEqual(orb.color, Orb._DEFAULT_COLOR)
        self.assertAlmostEqual(float(orb.radius), 32.0)
        self.assertAlmostEqual(float(orb.center.x), 40.0)
        self.assertAlmostEqual(float(orb.center.y), 50.0)
        self.assertAlmostEqual(orb.amount, 1.0)
        self.assertAlmostEqual(orb.glow, 1.0)
        self.assertAlmostEqual(orb.phase, 0.0)
        self.assertAlmostEqual(float(orb.soft_edge), 0.35)

    def test_moon_like_recipe(self):
        orb = Orb(
            center=(10, 20), radius=26, color="silver",
            glow=1.15, phase=0.15, soft_edge=0.1,
        )
        from scena.color import Color
        expected = tuple(float(c) for c in Color("silver").rgb[:3])
        self.assertEqual(orb.color, expected)
        self.assertAlmostEqual(orb.glow, 1.15)
        self.assertAlmostEqual(orb.phase, 0.15)
        self.assertAlmostEqual(float(orb.soft_edge), 0.1)

    def test_color_setter(self):
        orb = Orb(center=(0, 0))
        orb.color = "gold"
        from scena.color import Color
        expected = tuple(float(c) for c in Color("gold").rgb[:3])
        self.assertEqual(orb.color, expected)

    def test_collision_is_felt_body(self):
        orb = Orb(center=(0, 0), radius=50)
        spec = orb._collision_specs()[0]
        self.assertEqual(spec[0], "circle")
        self.assertAlmostEqual(spec[3], 50.0)

    def test_aabb_pads_glow_not_collision(self):
        tight = Orb(center=(0, 0), radius=40, glow=0.0)
        halo = Orb(center=(0, 0), radius=40, glow=2.0)
        t = tight._domain_aabb()
        h = halo._domain_aabb()
        self.assertAlmostEqual(t[2] - t[0], 80.0)
        self.assertGreater(h[2] - h[0], t[2] - t[0])
        self.assertAlmostEqual(tight._collision_specs()[0][3], 40.0)
        self.assertAlmostEqual(halo._collision_specs()[0][3], 40.0)

    def test_draw_full_and_crescent(self):
        import skia
        surf = skia.Surface.MakeRasterN32Premul(96, 96)
        canvas = surf.getCanvas()
        Orb(center=(48, 48), radius=20).draw(canvas)
        Orb(center=(48, 48), radius=20, phase=0.4, glow=1.15).draw(canvas)


class TestWarp(SpatialFxTestBase):
    def test_defaults_and_point_domain(self):
        w = Warp(center=(40, 50), radius=32)
        self.assertAlmostEqual(float(w.radius), 32.0)
        self.assertAlmostEqual(float(w.center.x), 40.0)
        self.assertAlmostEqual(float(w.center.y), 50.0)
        self.assertEqual(w.color, (0.45, 0.55, 1.0))
        self.assertIsNone(w.color2)
        self.assertAlmostEqual(w.amount, 1.0)
        self.assertAlmostEqual(w.speed, 1.0)
        self.assertAlmostEqual(w.twist, 0.35)
        self.assertEqual(w.spokes, 6)
        self.assertAlmostEqual(w.core, 1.0)
        self.assertIs(w.into, True)
        self.assertAlmostEqual(w.spin, 0.0)
        self.assertAlmostEqual(w.glow, 0.8)
        self.assertAlmostEqual(float(w.soft_edge), 0.35)
        self.assertTrue(w.is_alive)

    def test_live_mutation(self):
        w = Warp(center=(10, 20), radius=40, color="cyan")
        self.assertEqual(w.color, (0.0, 1.0, 1.0))
        w.color = "gold"
        from scena.color import Color
        expected = tuple(float(c) for c in Color("gold").rgb[:3])
        self.assertEqual(w.color, expected)
        w.color2 = "navy"
        w.amount = 1.4
        w.speed = 0.5
        w.twist = 1.1
        w.core = 0.0
        w.spin = 0.7
        w.glow = 0.2
        w.into = False
        self.assertIs(w.into, False)
        self.assertAlmostEqual(w.amount, 1.4)
        self.assertAlmostEqual(w.core, 0.0)
        w.color2 = None
        self.assertIsNone(w.color2)

    def test_spokes_clamp_on_write(self):
        w = Warp(center=(0, 0))
        w.spokes = 2
        self.assertEqual(w.spokes, 3)
        w.spokes = 30
        self.assertEqual(w.spokes, 24)
        w.spokes = 6.7
        self.assertEqual(w.spokes, 7)

    def test_spokes_bad_type(self):
        w = Warp(center=(0, 0))
        with self.assertRaises(TypeError):
            w.spokes = "many"

    def test_into_bool_only(self):
        w = Warp(center=(0, 0), into=False)
        self.assertIs(w.into, False)
        w.into = True
        self.assertIs(w.into, True)
        with self.assertRaises(TypeError):
            w.into = "out"
        with self.assertRaises(TypeError):
            w.into = 1
        with self.assertRaises(TypeError):
            Warp(center=(0, 0), into="into")

    def test_no_style(self):
        with self.assertRaises(TypeError):
            Warp(center=(0, 0), style="tunnel")

    def test_unknown_kwarg(self):
        with self.assertRaises(TypeError) as ctx:
            Warp(center=(0, 0), pan_response=0.2)
        self.assertIn("pan_response", str(ctx.exception))

    def test_collision_is_felt_body_not_glow(self):
        w = Warp(center=(0, 0), radius=50, glow=2.0)
        spec = w._collision_specs()[0]
        self.assertEqual(spec[0], "circle")
        self.assertAlmostEqual(spec[3], 45.0)
        aabb = w._domain_aabb()
        self.assertGreater(aabb[2] - aabb[0], 100.0)

    def test_not_a_background_field(self):
        from scena.background import BackgroundField
        w = Warp(center=(0, 0))
        self.assertNotIsInstance(w, BackgroundField)
        with self.assertRaises(TypeError) as ctx:
            canvas.background = w
        self.assertIn("SpatialFx", str(ctx.exception))
        with self.assertRaises(TypeError):
            canvas.set_fly(w)

    def test_amount_overshoot_stored(self):
        w = Warp(center=(0, 0))
        w.amount = 9.0
        self.assertAlmostEqual(w.amount, 9.0)

    def test_draw_does_not_raise(self):
        import skia
        w = Warp(center=(48, 48), radius=24)
        surf = skia.Surface.MakeRasterN32Premul(96, 96)
        w.draw(surf.getCanvas())


def _raster(w: int, h: int):
    import skia
    surf = skia.Surface.MakeRasterN32Premul(w, h)
    surf.getCanvas().clear(skia.Color4f(0, 0, 0, 1))
    return surf


def _pixels(surf):
    import skia
    return surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)


class _QualityMixin:
    """Run a block at one FxQuality, then restore the previous one."""

    def at_quality(self, q):
        from contextlib import contextmanager
        from scena.fx_quality import activate_quality, active_fx_quality

        @contextmanager
        def ctx():
            prev = active_fx_quality()
            activate_quality(q)
            try:
                yield
            finally:
                activate_quality(prev)
        return ctx()


class TestPortal(_QualityMixin, SpatialFxTestBase):
    def test_defaults_and_point_domain(self):
        p = Portal(center=(40, 50), radius=32)
        self.assertAlmostEqual(float(p.radius), 32.0)
        self.assertAlmostEqual(float(p.center.x), 40.0)
        self.assertEqual(p.color, (0.2, 0.65, 1.0))
        self.assertIsNone(p.color2)
        self.assertAlmostEqual(p.amount, 1.0)
        self.assertAlmostEqual(p.speed, 1.0)
        self.assertAlmostEqual(p.thickness, 0.25)
        self.assertAlmostEqual(p.chaos, 1.0)
        self.assertAlmostEqual(p.tilt, 0.0)
        self.assertAlmostEqual(p.angle, 0.0)
        self.assertAlmostEqual(p.glow, 0.8)
        self.assertAlmostEqual(float(p.soft_edge), 0.3)
        self.assertTrue(p.is_alive)

    def test_zero_arg(self):
        p = Portal()
        self.assertAlmostEqual(float(p.radius), 60.0)

    def test_live_mutation_and_colors(self):
        p = Portal(center=(0, 0), color="cyan")
        self.assertEqual(p.color, (0.0, 1.0, 1.0))
        p.color = None
        self.assertEqual(p.color, (0.2, 0.65, 1.0))
        p.color2 = "white"
        self.assertEqual(p.color2, (1.0, 1.0, 1.0))
        p.color2 = None
        self.assertIsNone(p.color2)
        p.tilt = 45
        p.angle = 30
        p.amount = 1.5
        self.assertAlmostEqual(p.tilt, 45.0)

    def test_thickness_and_chaos_clamp(self):
        p = Portal(center=(0, 0), thickness=5, chaos=-1)
        self.assertAlmostEqual(p.thickness, 1.0)
        self.assertAlmostEqual(p.chaos, 0.0)
        p.thickness = 0.0
        p.chaos = 9
        self.assertAlmostEqual(p.thickness, 0.05)
        self.assertAlmostEqual(p.chaos, 2.0)

    def test_thickness_and_chaos_bad_values(self):
        p = Portal(center=(0, 0))
        with self.assertRaises(TypeError):
            p.thickness = "thin"
        with self.assertRaises(TypeError):
            p.chaos = True
        with self.assertRaises(ValueError):
            p.chaos = float("nan")

    def test_no_style(self):
        with self.assertRaises(TypeError):
            Portal(center=(0, 0), style="vortex")

    def test_unknown_kwarg_lists_valid(self):
        with self.assertRaises(TypeError) as ctx:
            Portal(center=(0, 0), twist=0.5)
        self.assertIn("twist", str(ctx.exception))
        self.assertIn("chaos", str(ctx.exception))

    def test_collision_is_ring_body_not_glow(self):
        p = Portal(center=(0, 0), radius=50, glow=2.0)
        spec = p._collision_specs()[0]
        self.assertEqual(spec[0], "circle")
        self.assertAlmostEqual(spec[3], 50 * 1.035)
        aabb = p._domain_aabb()
        self.assertGreater(aabb[2] - aabb[0], 200.0)

    def test_tilted_collision_is_foreshortened_ellipse(self):
        import math
        p = Portal(center=(10, 20), radius=50, tilt=60, angle=30)
        kind, cx, cy, rx, ry, ang = p._collision_specs()[0]
        self.assertEqual(kind, "ellipse")
        self.assertAlmostEqual(rx, 50 * 1.035)
        self.assertAlmostEqual(ry, 50 * 1.035 * math.cos(math.radians(60)))
        self.assertAlmostEqual(ang, math.radians(30))

    def test_not_a_background_field(self):
        p = Portal(center=(0, 0))
        with self.assertRaises(TypeError):
            canvas.background = p

    def test_draw_each_quality(self):
        for q in ("low", "medium", "high", "max"):
            with self.subTest(q=q), self.at_quality(q):
                p = Portal(center=(48, 48), radius=24, tilt=40)
                p.draw(_raster(96, 96).getCanvas())
                p.destroy()

    def test_band_is_brighter_than_hole_and_outside(self):
        # Face-on: the ring band lights up; the hole and the far field stay dark.
        surf = _raster(160, 160)
        Portal(center=(80, 80), radius=40, chaos=0.0, glow=0.3).draw(surf.getCanvas())
        px = _pixels(surf).astype(float)
        lum = px[..., :3].sum(axis=2)
        band = lum[80, 120]          # on the ring (x = 80 + 40)
        hole = lum[80, 80]
        outside = lum[5, 5]
        self.assertGreater(band, hole + 120)
        self.assertGreater(band, outside + 120)

    def test_draws_nothing_outside_domain(self):
        surf = _raster(400, 400)
        p = Portal(center=(200, 200), radius=40, glow=0.5)
        p.draw(surf.getCanvas())
        x0, y0, x1, y1 = p._domain_aabb()
        px = _pixels(surf)[..., :3].sum(axis=2)
        self.assertEqual(px[:int(y0) - 1, :].max(), 0)
        self.assertEqual(px[:, int(x1) + 2:].max(), 0)

    def test_derived_color2_keeps_the_authors_hue(self):
        import colorsys
        from scena.spatial_fx_effects import (
            _PORTAL_DEFAULT_COLOR2, _portal_color2,
        )
        # Zero-arg ring drifts blue -> violet (the signature look) ...
        self.assertEqual(_portal_color2(Portal(center=(0, 0)).color), _PORTAL_DEFAULT_COLOR2)
        # ... but a color the author chose never turns into another hue.
        for name in ("orange", "lime", "magenta", "cyan"):
            with self.subTest(color=name):
                rgb = Portal(center=(0, 0), color=name).color
                h1, _, _ = colorsys.rgb_to_hsv(*rgb)
                h2, s2, _ = colorsys.rgb_to_hsv(*_portal_color2(rgb))
                self.assertAlmostEqual(h1, h2, places=6)
                self.assertGreater(min(_portal_color2(rgb)), min(rgb) - 1e-9)

    def test_turbulence_never_moves_the_ring(self):
        # Bug class: displacing the sample point (not just its color) turned
        # the ring into a lumpy blob. At full chaos the band must stay on the
        # circle at every angle, the hole stays dark, the outside stays dim.
        import math
        surf = _raster(240, 240)
        Portal(center=(120, 120), radius=80, chaos=2.0, glow=0.3).draw(surf.getCanvas())
        lum = _pixels(surf)[..., :3].astype(float).sum(axis=2)

        def at(rad, deg):
            a = math.radians(deg)
            return lum[int(round(120 - rad * math.sin(a))), int(round(120 + rad * math.cos(a)))]

        for deg in range(0, 360, 15):
            with self.subTest(deg=deg):
                ring = max(at(80 + dr, deg) for dr in (-2, -1, 0, 1, 2))
                self.assertGreater(ring, 150)
                self.assertGreater(ring, 2.5 * at(52, deg))
                self.assertGreater(ring, 2.5 * at(112, deg))

    def test_style_quality_ladder(self):
        p = Portal(center=(0, 0))
        got = {}
        for q in ("low", "medium", "high", "max"):
            with self.at_quality(q):
                got[q] = p._quality_steps()
        self.assertEqual(got["high"], got["max"])
        self.assertLess(got["medium"], got["high"])
        self.assertLess(got["low"], got["medium"])


class TestFireBlaze(_QualityMixin, SpatialFxTestBase):
    def test_is_directed_fire(self):
        f = Fire(style="blaze", center=(10, 20), width=30, length=90, angle=60)
        self.assertIsInstance(f, Fire)
        self.assertAlmostEqual(float(f.width), 30.0)
        self.assertAlmostEqual(float(f.length), 90.0)
        self.assertAlmostEqual(float(f.angle), 60.0)

    def test_default_length_ratio(self):
        f = Fire(style="blaze", center=(0, 0), width=40)
        self.assertAlmostEqual(float(f.length), 40 * 2.4)

    def test_radius_refused(self):
        with self.assertRaises(TypeError):
            Fire(style="blaze", center=(0, 0), radius=30)

    def test_collider_is_plumes_taller_and_slimmer(self):
        from scena.spatial_fx_effects import _LookPlume
        for width, length, angle in ((40, 100, 90), (26, 62, 30), (60, 150, -45)):
            with self.subTest(width=width, length=length, angle=angle):
                b = Fire(style="blaze", center=(10, 20), width=width,
                         length=length, angle=angle)._collision_specs()[0]
                p = _LookPlume(center=(10, 20), width=width,
                               length=length, angle=angle)._collision_specs()[0]
                self.assertEqual(b[0], "ellipse")
                self.assertAlmostEqual(b[3] / p[3], 1.25)   # along the flame
                self.assertAlmostEqual(b[4] / p[4], 0.7)    # across it
                self.assertAlmostEqual(b[5], p[5])
                # The base stays at the hearth; only the tip end grows.
                import math
                ux, uy = math.cos(b[5]), math.sin(b[5])
                base_b = (b[1] - ux * b[3], b[2] - uy * b[3])
                base_p = (p[1] - ux * p[3], p[2] - uy * p[3])
                self.assertAlmostEqual(base_b[0], base_p[0], places=6)
                self.assertAlmostEqual(base_b[1], base_p[1], places=6)

    def test_draw_each_quality(self):
        for q in ("low", "medium", "high", "max"):
            with self.subTest(q=q), self.at_quality(q):
                f = Fire(style="blaze", center=(40, 10), width=16, length=40)
                f._tick(1 / 60, 0.0)
                f.draw(_raster(80, 80).getCanvas())
                f.destroy()

    def test_medium_and_low_draw_the_plume_look(self):
        from unittest import mock
        from scena.spatial_fx_effects import _LookPlume
        f = Fire(style="blaze", center=(40, 10), width=16, length=40)
        for q, plume in (("low", True), ("medium", True), ("high", False), ("max", False)):
            with self.subTest(q=q), self.at_quality(q), \
                    mock.patch.object(_LookPlume, "draw") as draw:
                f.draw(_raster(80, 80).getCanvas())
                self.assertEqual(draw.called, plume)

    def test_high_runs_no_particles(self):
        f = Fire(style="blaze", center=(40, 10), width=16, length=40)
        with self.at_quality("medium"):
            for _ in range(30):
                f._tick(1 / 60, 0.0)
            self.assertGreater(f._bank.n, 0)
        with self.at_quality("high"):
            f._tick(1 / 60, 0.0)
            self.assertEqual(f._bank.n, 0)

    def test_plate_follows_zoom_and_res(self):
        f = Fire(style="blaze", center=(0, 0), width=40, length=100)
        with self.at_quality("high"):
            _, (pw1, ph1), _, _, _, steps_h = f._plate_frame(1.0)
            _, (pw2, ph2), _, _, _, _ = f._plate_frame(2.0)
        with self.at_quality("max"):
            _, (pwm, phm), _, _, _, steps_m = f._plate_frame(1.0)
        self.assertAlmostEqual(pw2 / pw1, 2.0, delta=0.1)
        self.assertAlmostEqual(pwm / pw1, 2.0, delta=0.1)
        self.assertEqual((steps_h, steps_m), (32.0, 50.0))

    def test_plate_bucket_absorbs_wobble_and_caps(self):
        f = Fire(style="blaze", center=(0, 0), width=40, length=100)
        with self.at_quality("high"):
            buckets = {f._plate_frame(1.0 + k * 0.004)[2] for k in range(-3, 4)}
            self.assertEqual(len(buckets), 1)
            big = f._plate_frame(400.0)
        self.assertLessEqual(max(big[2]), 1024)
        self.assertLessEqual(big[1][0], big[2][0])

    def test_plate_surface_reused_across_frames(self):
        f = Fire(style="blaze", center=(40, 10), width=16, length=40)
        with self.at_quality("high"):
            f.draw(_raster(80, 80).getCanvas())
            first = f._plate_cache[1]
            self.advance()
            f.draw(_raster(80, 80).getCanvas())
            self.assertIs(f._plate_cache[1], first)

    def test_high_matches_max_brightness(self):
        # Brightness is normalised by step count: 32-step ½-res high must read
        # like the 50-step full-res reference.
        import skia
        means = {}
        for q in ("high", "max"):
            with self.at_quality(q):
                surf = _raster(120, 160)
                c = surf.getCanvas()
                c.scale(1.5, 1.5)
                f = Fire(style="blaze", center=(40, 8), width=24, length=80)
                f.draw(c)
                f.destroy()
                means[q] = _pixels(surf)[..., :3].astype(float).mean()
        self.assertGreater(means["max"], 3.0)
        self.assertLess(abs(means["high"] - means["max"]) / means["max"], 0.25)


class TestShaderTimeIsWrapped(_QualityMixin, SpatialFxTestBase):
    """Bug class: a raw, growing clock times a turbulence frequency loses all
    GPU sin/cos precision within minutes (Intel collapses at |x| ≥ 2^17).
    New shader kinds take time only as CPU-wrapped phases."""

    def test_wrapped_phase_range_and_continuity(self):
        import math
        for t in (0.0, 1.0, 3600.0, 1e7):
            for rate in (0.35, 4.2, -13.0, 120.0):
                ph = sfx._wrapped_phase(rate, t)
                self.assertGreaterEqual(ph, 0.0)
                self.assertLess(ph, 2 * math.pi)
                nxt = sfx._wrapped_phase(rate, t + 1 / 60)
                step = (nxt - ph) % (2 * math.pi)
                expect = (rate / 60) % (2 * math.pi)
                self.assertAlmostEqual(step, expect, places=5)

    def _bound_uniforms(self, fx, builder_name):
        """Every uniform the draw binds, via a recording proxy for the builder."""
        from unittest import mock
        from scena import spatial_fx_effects as effects
        real = getattr(effects, builder_name)
        seen = {}

        class Recorder:
            def setUniform(self, name, value):
                seen[name] = value
                return real.setUniform(name, value)

            def makeShader(self, *a, **k):
                return real.makeShader(*a, **k)

        with mock.patch.object(effects, builder_name, Recorder()):
            fx.draw(_raster(64, 64).getCanvas())
        return seen

    def test_uniforms_stay_small_after_a_long_run(self):
        import math
        self.t = 1e7  # ~4 months of uptime
        cases = (
            (Portal(center=(32, 32), radius=16, speed=3.0), "portal_builder"),
            (Fire(style="blaze", center=(32, 4), width=12, length=30, speed=3.0), "blaze_builder"),
        )
        with self.at_quality("high"):
            for fx, builder in cases:
                with self.subTest(fx=type(fx).__name__):
                    seen = self._bound_uniforms(fx, builder)
                    self.assertTrue(seen)
                    for name, value in seen.items():
                        vals = value if isinstance(value, (list, tuple)) else [value]
                        for v in vals:
                            self.assertTrue(math.isfinite(v), name)
                            self.assertLess(abs(v), 1e4, name)


class TestEntityParity(SpatialFxTestBase):
    """Entity surface: collidable, groups, id lock — shared with Shape."""

    def test_is_entity(self):
        from scena.shapes import Entity, Shape
        c = Fire(center=(10, 10))
        self.assertIsInstance(c, Entity)
        self.assertNotIsInstance(c, Shape)

    def test_collidable_opts_in(self):
        from scena.collision import get_collision_system, reset_collision_system
        reset_collision_system()
        c = Fire(center=(50, 50), radius=20)
        self.assertFalse(c.collidable)
        c.collidable = True
        self.assertTrue(c.collidable)
        self.assertIsNotNone(c._collider)
        ids = [col._identity for col in get_collision_system()._colliders]
        self.assertIn(c, ids)
        c.collidable = False
        self.assertIsNone(c._collider)
        reset_collision_system()

    def test_on_collide_opts_in(self):
        from scena.collision import reset_collision_system
        reset_collision_system()
        c = Fire(center=(0, 0), radius=10)
        calls = []
        c.on_collide = lambda me, other, info: calls.append(me)
        self.assertTrue(c.collidable)
        self.assertIsNotNone(c._collider)
        reset_collision_system()

    def test_add_remove_group(self):
        c = Fire(center=(0, 0))
        c.add_to_group("emitters")
        self.assertIn("emitters", c.group)
        members = canvas._engine.registry.list_by_groupid("emitters")
        self.assertIn(c, members)
        c.remove_from_group("emitters")
        self.assertNotIn("emitters", c.group)


def _exported_fx_calls():
    """``(label, factory, point keyword)`` for every exported SpatialFx kind.

    Walks ``scena.__all__`` so a new kind is covered without editing this
    list; each Fire style is its own class and gets its own row.
    """
    import inspect
    import scena
    from scena.spatial_fx import SpatialFx as _Base
    from scena.spatial_fx_effects import FIRE_STYLES
    rows = []
    for name in scena.__all__:
        cls = getattr(scena, name, None)
        if not (inspect.isclass(cls) and issubclass(cls, _Base)) or cls is _Base:
            continue
        key = "p1=" if name in ("Rain", "Jet") else "center="
        if cls is Fire:
            for style in FIRE_STYLES:
                rows.append((f"Fire[{style}]",
                             lambda *a, _s=style, **k: Fire(*a, style=_s, **k), key))
        else:
            rows.append((name, cls, key))
    return rows


class TestKeywordOnlyPlacement(SpatialFxTestBase):
    """SpatialFx places by points, like its Shape siblings (Circle, Rect, Line).

    Bug class: a kind that takes positional numbers, ``at=``, or a scalar
    placement keyword (``x=`` / ``x1=`` / ``pos=``) — a second spelling of
    ``center=`` / ``p1=``. Every exported kind must refuse them with an
    orientation naming the point keyword, before anything is placed.
    """

    SCALAR_KEYS = ("at", "x", "y", "x1", "y1", "pos", "position")

    def test_kinds_are_covered(self):
        names = {label.split("[")[0] for label, _f, _k in _exported_fx_calls()}
        self.assertTrue({"Fire", "Rain", "Jet", "Sparks", "GlowSpot", "Orb",
                         "Sunburst", "Starburst", "Warp"} <= names)

    def test_positional_numbers_raise_with_example(self):
        for label, make, key in _exported_fx_calls():
            for args in ((200, 150), (200, 150, 40), ((200, 150),), (0, 0, 100, 100)):
                with self.subTest(kind=label, args=args):
                    before = registered_count()
                    with self.assertRaises(TypeError) as ctx:
                        make(*args)
                    msg = str(ctx.exception)
                    self.assertIn("keyword arguments only", msg)
                    self.assertIn(key, msg)
                    self.assertNotIn("_", msg.split("(")[0])  # public name, not _LookPlume
                    self.assertEqual(registered_count(), before)

    def test_scalar_and_at_keywords_raise_with_hint(self):
        for label, make, key in _exported_fx_calls():
            for kw in self.SCALAR_KEYS:
                value = (10, 20) if kw in ("at", "pos", "position") else 10
                with self.subTest(kind=label, kw=kw):
                    before = registered_count()
                    with self.assertRaises(TypeError) as ctx:
                        make(**{kw: value})
                    msg = str(ctx.exception)
                    self.assertIn("is placed by", msg)
                    self.assertIn(key, msg)
                    self.assertEqual(registered_count(), before)

    def test_help_signature_has_no_positional_catchall(self):
        import inspect
        for label, make, _key in _exported_fx_calls():
            cls = make if inspect.isclass(make) else type(make())
            with self.subTest(kind=label):
                params = inspect.signature(cls.__init__).parameters.values()
                self.assertFalse(
                    any(p.kind is p.VAR_POSITIONAL for p in params),
                    f"{label} shows *args in help()",
                )

    def test_center_link_still_works_for_point_kinds(self):
        ship = Circle(center=(100, 200), radius=10)
        for label, make, key in _exported_fx_calls():
            if key != "center=":
                continue
            with self.subTest(kind=label):
                fx = make(center=lambda: ship.center)
                self.assertAlmostEqual(float(fx.center.x), 100.0)
                fx.destroy()


class TestRainCorners(SpatialFxTestBase):
    def test_p1_p2_corners(self):
        r = Rain(p1=(10, 20), p2=(110, 70))
        self.assertEqual(r.model, PadModel.CORNER_CORNER)
        self.assertEqual(r._domain_aabb(), (10.0, 20.0, 110.0, 70.0))
        self.assertAlmostEqual(float(r.width), 100.0)
        self.assertAlmostEqual(float(r.center.y), 45.0)

    def test_p1_p2_link(self):
        a = Circle(center=(0, 0), radius=4)
        r = Rain(p1=lambda: a.center, p2=(100, 50))
        a.center = (20, 10)
        self.assertEqual(r._domain_aabb()[:2], (20.0, 10.0))

    def test_one_corner_raises(self):
        for kw in ({"p1": (0, 0)}, {"p2": (5, 5)}):
            with self.subTest(kw=kw):
                with self.assertRaises(TypeError) as ctx:
                    Rain(**kw)
                self.assertIn("pairs", str(ctx.exception))

    def test_corners_and_center_raise(self):
        with self.assertRaises(TypeError):
            Rain(p1=(0, 0), p2=(10, 10), center=(5, 5))

    def test_no_angle(self):
        with self.assertRaises(TypeError) as ctx:
            Rain(center=(0, 0), width=40, height=20, angle=30)
        self.assertIn("no angle", str(ctx.exception))
        self.assertFalse(hasattr(Rain, "angle"))

    def test_from_rect_still_follows(self):
        plat = Rect(center=(100, 100), width=80, height=20)
        r = Rain.from_rect(plat)
        self.assertEqual(r._domain_aabb(), (60.0, 90.0, 140.0, 110.0))
        plat.center = (200, 100)
        self.assertEqual(r._domain_aabb()[0], 160.0)


class TestDualModelDerivates(SpatialFxTestBase):
    """Bug class: a dual-model domain whose Derivate parts read stale.

    Pad / beam domains lacked ``_materialize_derivate_part``, so
    ``Rain(p1=, p2=).width`` read 0 and ``Rain(center=…).p1`` read the origin.
    Every part the other model defines must read its derived value.
    """

    def _xy(self, p):
        return (round(float(p.x), 6), round(float(p.y), 6))

    def test_rain_corner_model_derives_center_size(self):
        r = Rain(p1=(10, 20), p2=(110, 70))
        self.assertEqual(self._xy(r.center), (60.0, 45.0))
        self.assertAlmostEqual(float(r.width), 100.0)
        self.assertAlmostEqual(float(r.height), 50.0)

    def test_rain_center_model_derives_corners(self):
        r = Rain(center=(50, 50), width=40, height=20)
        self.assertEqual(self._xy(r.p1), (30.0, 40.0))
        self.assertEqual(self._xy(r.p2), (70.0, 60.0))

    def test_jet_models_derive_each_other(self):
        pp = Jet(p1=(0, 0), p2=(30, 40))
        self.assertEqual(self._xy(pp.origin), (0.0, 0.0))
        self.assertAlmostEqual(float(pp.length), 50.0)
        oal = Jet(origin=(0, 0), angle=0, length=50)
        self.assertEqual(self._xy(oal.p1), (0.0, 0.0))
        self.assertEqual(self._xy(oal.p2), (50.0, 0.0))


class TestJetPairs(SpatialFxTestBase):
    def test_p1_alone_raises_not_origin(self):
        # Used to become origin= silently (a rewrite of what the author wrote).
        for kw in ({"p1": (0, 0)}, {"p2": (5, 5)}):
            with self.subTest(kw=kw):
                with self.assertRaises(TypeError) as ctx:
                    Jet(**kw)
                self.assertIn("origin=", str(ctx.exception))

    def test_points_and_origin_raise(self):
        with self.assertRaises(TypeError):
            Jet(p1=(0, 0), p2=(10, 0), origin=(0, 0))


class TestDefaultPlacementFollowsDesign(unittest.TestCase):
    """No ``center=`` / ``origin=`` → the design center, for any design size.

    It once read ``canvas.design_width`` (no such field); a bare ``except``
    turned that into a fixed (200, 150) — the center of the tests' 400×300,
    so suites at that size never saw it.
    """

    def tearDown(self):
        init(width=800, height=600)

    def test_every_spatial_fx_defaults_to_the_design_center(self):
        import inspect
        import scena
        from scena.spatial_fx import SpatialFx
        kinds = [getattr(scena, n) for n in scena.__all__
                 if inspect.isclass(getattr(scena, n, None))
                 and issubclass(getattr(scena, n), SpatialFx)
                 and getattr(scena, n) is not SpatialFx
                 and not inspect.isabstract(getattr(scena, n))]
        self.assertGreaterEqual(len(kinds), 10)
        for w, h in ((640, 360), (2000, 1200)):
            init(width=w, height=h)
            for cls in kinds:
                with self.subTest(cls=cls.__name__, size=(w, h)):
                    fx = cls()
                    anchor = getattr(fx, "origin", None) if cls.__name__ == "Jet" else fx.center
                    self.assertAlmostEqual(float(anchor.x), w / 2)
                    self.assertAlmostEqual(float(anchor.y), h / 2)
                    fx.destroy()


class TestSpatialFxRunOnWorldTime(unittest.TestCase):
    """SpatialFx are world actors: pause and slow motion reach their tick and
    their shader phases, as they reach their own ``after`` / ``every``
    (design decision, review 2026-10-09 S1-7). The production clock is read
    here: SystemWorld does not pin it."""

    def test_production_clock_is_world_time(self):
        from scena import clock
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            w.step(3, dt=1 / 60)
            self.assertEqual(sfx._now(), clock.time)
            self.assertEqual(sfx._shader_time(), clock.time)

    def test_paused_world_freezes_the_emitter(self):
        from scena import clock
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            s = Sparks(center=(100, 100), radius=40, rate=80)
            try:
                w.step(1, dt=1 / 60)
                n0 = s._bank.n
                t0 = sfx._shader_time()
                clock.paused = True
                w.step(30, dt=1 / 60)
                self.assertEqual(s._bank.n, n0, "a paused world kept emitting")
                self.assertEqual(sfx._shader_time(), t0)
                clock.paused = False
                w.step(20, dt=1 / 60)
                self.assertGreater(s._bank.n, n0)
            finally:
                clock.paused = False
                s.destroy()


if __name__ == "__main__":
    unittest.main()