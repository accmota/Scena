"""Unit tests for shape-local transient effects."""
from __future__ import annotations

import unittest
import warnings
import weakref

import skia

from scena import init
from scena.shapes import Circle, Line, Rect, RegularPolygon, Ellipse
from scena.recipes import Neon
from scena.filters import GlowFilter
from scena import transients as tx

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _clock():
    """Mutable fake time for deterministic tests."""
    state = {"t": 100.0}

    def now():
        return state["t"]

    def set_t(t):
        state["t"] = float(t)

    def advance(dt):
        state["t"] += float(dt)

    return now, set_t, advance


class TransientTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def setUp(self):
        self.now, self.set_t, self.advance = _clock()
        tx.set_now_fn(self.now)
        # drop any leaked registrations
        for s in list(tx._active_shapes):
            tx.clear_transients(s)

    def tearDown(self):
        for s in list(tx._active_shapes):
            tx.clear_transients(s)
        tx.set_now_fn(None)


class TestChannelsAndAPI(TransientTestBase):
    def test_each_method_installs_only_its_channel(self):
        c = Circle(center=(50, 50), radius=12)
        c.dissolve_out(0.5)
        st = c._tx_state
        self.assertIsNotNone(st.life)
        self.assertIsNone(st.flash)
        c.flash()
        self.assertIsNotNone(st.flash)
        self.assertIsNotNone(st.life)
        c.pulse_outline()
        self.assertIsNotNone(st.pulse)
        c.pop()
        self.assertIsNotNone(st.pop)
        self.assertEqual(st.life.kind, "dissolve")

    def test_stack_hits_and_life(self):
        c = Circle(center=(40, 40), radius=10)
        c.dissolve_out(1.0)
        c.flash(0.5)
        c.pulse_outline(duration=0.5)
        c.pop(duration=0.5)
        c.knock(distance=12, angle=30, duration=0.5)
        c.spark_burst(duration=0.5)
        st = c._tx_state
        self.assertTrue(st.any_active())
        self.assertIsNotNone(st.life)
        self.assertIsNotNone(st.flash)
        self.assertIsNotNone(st.pulse)
        self.assertIsNotNone(st.pop)
        self.assertIsNotNone(st.knock)
        self.assertIsNotNone(st.spark)

    def test_replace_same_channel_fires_first_on_done_cancelled(self):
        done = []
        c = Circle(center=(10, 10), radius=8)
        h1 = c.dissolve_out(0.5, on_done=lambda s: done.append("first"))
        h2 = c.dissolve_out(0.5, on_done=lambda s: done.append("second"))
        self.assertEqual(done, ["first"])
        self.assertTrue(h1.cancelled)
        self.assertTrue(h1.done)
        self.assertFalse(h2.cancelled)
        self.assertFalse(h2.done)
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, ["first", "second"])
        self.assertFalse(h2.cancelled)
        self.assertTrue(h2.done)

    def test_burn_replaces_dissolve(self):
        c = Circle(center=(20, 20), radius=10)
        c.dissolve_out(0.8)
        self.assertEqual(c._tx_state.life.kind, "dissolve")
        c.burn_out(0.8)
        self.assertEqual(c._tx_state.life.kind, "burn")

    def test_burn_out_fidelity_is_retired_with_the_fix(self):
        # 0.6.0: fidelity= never changed the drawing; the old spelling names
        # the fix instead of being silently ignored.
        import inspect
        c = Circle(center=(20, 20), radius=10)
        with self.assertRaises(TypeError) as cm:
            c.burn_out(0.5, fidelity="full")
        msg = str(cm.exception)
        self.assertIn("fidelity", msg)
        self.assertIn("removed in 0.6.0", msg)
        self.assertIn("burn_out(0.55)", msg)
        self.assertIsNone(getattr(c, "_tx_state", None) and c._tx_state.life)
        with self.assertRaises(TypeError) as cm:
            c.burn_out(0.5, intensty=2)
        self.assertIn("Valid: duration, intensity=, on_done=", str(cm.exception))
        self.assertEqual(
            list(inspect.signature(c.burn_out).parameters),
            ["duration", "intensity", "on_done"],
        )

    def test_returns_channel_handle(self):
        c = Circle(center=(1, 1), radius=5)
        h = c.flash()
        self.assertIs(h, c._tx_state.flash)
        self.assertFalse(h.done)
        self.assertFalse(h.cancelled)
        self.assertIs(c.pop(), c._tx_state.pop)
        self.assertIs(c.pulse_outline(), c._tx_state.pulse)
        self.assertIs(c.spark_burst(), c._tx_state.spark)
        self.assertIs(c.dissolve_out(0.2), c._tx_state.life)
        self.assertIs(c.dissolve_in(0.2), c._tx_state.life)
        self.assertIs(c.fade_in(0.2), c._tx_state.life)
        self.assertIs(c.fade_out(0.2), c._tx_state.life)
        self.assertIs(c.implode(0.2), c._tx_state.life)
        self.assertIs(c.blink(0.2), c._tx_state.flash)
        self.assertIs(c.knock(distance=5, angle=0), c._tx_state.knock)
        self.assertIs(c.burn_out(0.2), c._tx_state.life)
        self.assertIs(c.clear_transients(), c)

    def test_life_spawn_replaces_death(self):
        """dissolve_in replaces dissolve_out on the shared life slot."""
        done = []
        c = Circle(center=(40, 40), radius=10)
        h1 = c.dissolve_out(1.0, on_done=lambda s: done.append("out"))
        h2 = c.dissolve_in(1.0, on_done=lambda s: done.append("in"))
        st = c._tx_state
        self.assertIs(st.life, h2)
        self.assertEqual(st.life.kind, "dissolve_in")
        self.assertTrue(h1.cancelled)
        self.assertEqual(done, ["out"])

    def test_life_chain_last_wins(self):
        """implode → fade_out → fade_in leaves only fade_in."""
        c = Circle(center=(40, 40), radius=10)
        h1 = c.implode(1.0)
        h2 = c.fade_out(1.0)
        h3 = c.fade_in(1.0)
        st = c._tx_state
        self.assertIs(st.life, h3)
        self.assertEqual(st.life.kind, "fade_in")
        self.assertTrue(h1.cancelled)
        self.assertTrue(h2.cancelled)
        self.assertFalse(h3.cancelled)

    def test_styles_install(self):
        c = Circle(center=(20, 20), radius=8)
        c.dissolve_out(0.5, style="vortex")
        self.assertEqual(c._tx_state.life.style, "vortex")
        c.dissolve_out(0.5, style="wipe", angle=90.0)
        self.assertEqual(c._tx_state.life.style, "wipe")
        self.assertAlmostEqual(c._tx_state.life.angle, 90.0)

    def test_implode_replaces_life(self):
        c = Circle(center=(20, 20), radius=10)
        c.dissolve_out(0.8)
        c.implode(0.4)
        self.assertEqual(c._tx_state.life.kind, "implode")

    def test_blink_replaces_flash(self):
        c = Circle(center=(20, 20), radius=10)
        c.flash(0.5)
        c.blink(0.5)
        self.assertEqual(c._tx_state.flash.kind, "blink")

    def test_blink_refresh_keeps_handle_and_phase(self):
        """Second blink extends the window; t0 / rate stay (no strobe hitch)."""
        done = []
        c = Circle(center=(20, 20), radius=10)
        h1 = c.blink(1.0, rate=8.0, intensity=0.4, on_done=lambda s: done.append("first"))
        t0 = h1.t0
        self.advance(0.4)
        h2 = c.blink(1.0, rate=3.0, intensity=0.9, on_done=lambda s: done.append("second"))
        self.assertIs(h2, h1)
        self.assertIs(c._tx_state.flash, h1)
        self.assertFalse(h1.cancelled)
        self.assertFalse(h1.done)
        self.assertEqual(done, [])
        self.assertAlmostEqual(h1.t0, t0)
        self.assertAlmostEqual(h1.rate, 8.0)
        self.assertAlmostEqual(h1.intensity, 0.9)
        self.assertAlmostEqual(h1.duration, 1.4)
        self.advance(0.5)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, [])
        self.assertFalse(h1.done)
        self.advance(0.6)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, ["second"])
        self.assertTrue(h1.done)
        self.assertFalse(h1.cancelled)

    def test_blink_refresh_does_not_shrink_remaining(self):
        c = Circle(center=(20, 20), radius=10)
        h = c.blink(2.0)
        self.advance(0.3)
        self.assertIs(c.blink(0.5), h)
        self.assertAlmostEqual(h.duration, 2.0)

    def test_blink_refresh_keeps_on_done_when_omitted(self):
        done = []
        c = Circle(center=(20, 20), radius=10)
        h = c.blink(1.0, on_done=lambda s: done.append("keep"))
        self.advance(0.4)
        c.blink(1.0)
        self.assertIs(c._tx_state.flash, h)
        self.assertEqual(done, [])
        self.advance(1.1)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, ["keep"])

    def test_flash_still_cancels_blink(self):
        done = []
        c = Circle(center=(20, 20), radius=10)
        h = c.blink(1.0, on_done=lambda s: done.append("blink"))
        c.flash(0.5, on_done=lambda s: done.append("flash"))
        self.assertTrue(h.cancelled)
        self.assertEqual(done, ["blink"])
        self.assertEqual(c._tx_state.flash.kind, "flash")

    def test_hit_channels_on_done(self):
        """Shape helpers forward on_done for flash/pulse/pop/etc."""
        done = []
        c = Circle(center=(30, 30), radius=10)
        c.flash(0.15, on_done=lambda s: done.append("flash"))
        c._tx_state.flash.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, ["flash"])

        done.clear()
        c.pulse_outline(duration=0.15, on_done=lambda s: done.append("pulse"))
        c._tx_state.pulse.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, ["pulse"])

        done.clear()
        c.pop(duration=0.15, on_done=lambda s: done.append("pop"))
        c._tx_state.pop.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, ["pop"])

        done.clear()
        c.blink(duration=0.15, on_done=lambda s: done.append("blink"))
        c._tx_state.flash.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, ["blink"])

        done.clear()
        c.knock(duration=0.15, distance=8, angle=0, on_done=lambda s: done.append("knock"))
        c._tx_state.knock.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, ["knock"])

        done.clear()
        c.spark_burst(duration=0.15, on_done=lambda s: done.append("spark"))
        c._tx_state.spark.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, ["spark"])

    def test_knock_stacks_with_pop(self):
        c = Circle(center=(20, 20), radius=10)
        c.pop(scale=1.35, duration=1.0)
        c.knock(distance=10, angle=90, duration=1.0)
        st = c._tx_state
        self.assertIsNotNone(st.pop)
        self.assertEqual(st.pop.kind, "pop")
        self.assertIsNotNone(st.knock)
        self.assertEqual(st.knock.kind, "knock")
        st.pop.t0 = self.now()
        st.knock.t0 = self.now()
        self.advance(0.1)
        mods = st.compose(self.now())
        self.assertNotAlmostEqual(mods.scale_mul, 1.0)
        self.assertTrue(abs(mods.offset_x) > 1e-3 or abs(mods.offset_y) > 1e-3)

    def test_repop_does_not_cancel_knock(self):
        c = Circle(center=(20, 20), radius=10)
        c.knock(distance=10, angle=0, duration=1.0)
        knock = c._tx_state.knock
        c.pop(scale=1.2, duration=1.0)
        self.assertIs(c._tx_state.knock, knock)
        self.assertFalse(knock.cancelled)
        self.assertIsNotNone(c._tx_state.pop)

    def test_flash_pop_knock_spark_all_active(self):
        c = Circle(center=(30, 30), radius=12)
        c.flash(0.5)
        c.pop(duration=0.5)
        c.knock(distance=8, angle=45, duration=0.5)
        c.spark_burst(duration=0.5)
        st = c._tx_state
        self.assertIsNotNone(st.flash)
        self.assertIsNotNone(st.pop)
        self.assertIsNotNone(st.knock)
        self.assertIsNotNone(st.spark)

    def test_clear_fires_on_done_cancelled(self):
        done = []
        c = Circle(center=(5, 5), radius=5)
        h = c.dissolve_out(1.0, on_done=lambda s: done.append(1))
        c.clear_transients()
        self.assertFalse(tx.has_active_transient(c))
        self.assertEqual(done, [1])
        self.assertTrue(h.cancelled)
        self.assertTrue(h.done)
        self.advance(2.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, [1])

    def test_destroy_silent_no_on_done(self):
        done = []
        c = Circle(center=(5, 5), radius=5)
        c.dissolve_out(1.0, on_done=lambda s: done.append(1))
        c.destroy()
        self.assertEqual(done, [])


class TestLifecycle(TransientTestBase):
    def test_replaced_on_done_that_destroys_leaves_no_registration(self):
        """S8 (system world machine): replacing a flash fires the old
        ``on_done``; if that destroys the shape, the new channel must not
        re-register the dead shape."""
        c = Circle(center=(30, 30), radius=10)
        c.flash(0.1, on_done=lambda: c.destroy())
        c.flash(0.1)
        self.assertFalse(c.is_alive)
        self.assertFalse(tx.is_registered(c))
        self.assertFalse(tx.has_active_transient(c))

    def test_transient_on_destroyed_shape_never_registers(self):
        done = []
        c = Circle(center=(30, 30), radius=10)
        c.destroy()
        for verb in (lambda: c.flash(0.1, on_done=lambda: done.append(1)),
                     lambda: c.pop(), lambda: c.dissolve_out(0.2)):
            verb()
            self.assertFalse(tx.is_registered(c))
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, [])

    def test_registry_on_start_and_finish(self):
        c = Circle(center=(30, 30), radius=10)
        self.assertFalse(tx.is_registered(c))
        c.flash(duration=0.1)
        self.assertTrue(tx.is_registered(c))
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertFalse(tx.has_active_transient(c))
        self.assertFalse(tx.is_registered(c))

    def test_exit_hides_and_on_done_once(self):
        done = []
        c = Circle(center=(30, 30), radius=10)
        c.dissolve_out(0.2, on_done=lambda s: done.append(s))
        self.assertTrue(c.visible)
        self.advance(0.5)
        tx.tick_all_transients(self.now())
        self.assertFalse(c.visible)
        self.assertEqual(done, [c])
        tx.tick_all_transients(self.now())
        self.assertEqual(done, [c])

    def test_draw_does_not_finish_lifecycle(self):
        done = []
        c = Circle(center=(30, 30), radius=10)
        c.dissolve_out(0.1, on_done=lambda s: done.append(1))
        self.advance(1.0)
        # paint past duration without tick
        surf = skia.Surface(128, 128)
        c.draw(surf.getCanvas())
        self.assertEqual(done, [])
        self.assertTrue(tx.has_active_transient(c))
        self.assertTrue(c.visible)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, [1])
        self.assertFalse(c.visible)

    def test_mid_duration_no_finish(self):
        done = []
        c = Circle(center=(30, 30), radius=10)
        t0 = self.now()
        c.dissolve_out(1.0, on_done=lambda s: done.append(1))
        # force t0 to our clock
        c._tx_state.life.t0 = t0
        self.advance(0.4)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, [])
        self.assertTrue(c.visible)
        p = c._tx_state.life.progress(self.now())
        self.assertGreater(p, 0.2)
        self.assertLess(p, 0.6)

    def test_on_done_bound_destroy(self):
        """Arity truncation: on_done=e.destroy calls destroy() with no extra arg."""
        c = Circle(center=(30, 30), radius=10)
        c.dissolve_out(0.1, on_done=c.destroy)
        c._tx_state.life.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertFalse(c.is_alive)

    def test_on_done_zero_arg_lambda(self):
        n = []
        c = Circle(center=(30, 30), radius=10)
        c.dissolve_out(0.1, on_done=lambda: n.append(1))
        c._tx_state.life.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(n, [1])
        self.assertFalse(c.visible)
        self.assertTrue(c.is_alive)

    def test_on_done_free_function_receives_shape(self):
        seen = []

        def die(ship):
            seen.append(ship)
            ship.destroy()

        c = Circle(center=(30, 30), radius=10)
        c.dissolve_out(0.1, on_done=die)
        c._tx_state.life.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(seen, [c])
        self.assertFalse(c.is_alive)

    def test_on_done_exception_propagates_after_finish(self):
        calls = []

        def boom(s):
            calls.append(1)
            raise RuntimeError("nope")

        a = Circle(center=(10, 10), radius=5)
        b = Circle(center=(80, 80), radius=5)
        done_b = []
        a.dissolve_out(0.1, on_done=boom)
        b.dissolve_out(0.1, on_done=lambda s: done_b.append(1))
        a._tx_state.life.t0 = self.now()
        b._tx_state.life.t0 = self.now()
        self.advance(1.0)
        with self.assertRaisesRegex(RuntimeError, "nope"):
            tx.tick_all_transients(self.now())
        self.assertFalse(a.visible)  # finish applied before on_done ran
        tx.tick_all_transients(self.now())  # b completes; a's on_done not re-run
        self.assertEqual(calls, [1])
        self.assertEqual(done_b, [1])
        self.assertFalse(b.visible)


class TestOrthogonality(TransientTestBase):
    def test_pulse_does_not_change_visual(self):
        neon = Neon("cyan")
        c = Circle(center=(50, 50), radius=15)
        c.visual = neon
        c.pulse_outline(duration=0.3)
        self.assertIs(c.visual, neon)
        surf = skia.Surface(128, 128)
        c.draw(surf.getCanvas())
        self.assertIs(c.visual, neon)
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertIs(c.visual, neon)

    def test_shared_neon_identity_while_dissolving(self):
        neon = Neon("cyan")
        a = Circle(center=(20, 20), radius=10).set_color("red")
        b = Circle(center=(80, 80), radius=10).set_color("blue")
        a.visual = neon
        b.visual = neon
        self.assertIs(a.visual, b.visual)
        a.dissolve_out(0.5)
        self.assertIs(a.visual, neon)
        self.assertIs(b.visual, neon)

    def test_pop_does_not_mutate_geometry(self):
        c = Circle(center=(100, 100), radius=20)
        rx, ry, rr = c.center.x, c.center.y, c.radius
        c.pop(scale=1.5, duration=0.2)
        c._tx_state.pop.t0 = self.now()
        self.advance(0.05)
        mods = tx.compose_draw_mods(c, self.now())
        self.assertIsNotNone(mods)
        self.assertNotAlmostEqual(mods.scale_mul, 1.0)
        self.assertAlmostEqual(c.center.x, rx)
        self.assertAlmostEqual(c.center.y, ry)
        self.assertAlmostEqual(c.radius, rr)

    def test_fill_unchanged_by_flash(self):
        c = Circle(center=(40, 40), radius=12).set_color("gold")
        before = id(c.fill)
        c.flash()
        self.assertEqual(id(c.fill), before)


class TestDrawSmoke(TransientTestBase):
    def _draw_ok(self, shape, times=(0.0, 0.35, 0.9)):
        t0 = self.now()
        st = shape._tx_state
        for name, ch in st.channels():
            ch.t0 = t0
        for dt in times:
            self.set_t(t0 + dt * max(
                (ch.duration for _, ch in st.channels()),
                default=0.5,
            ))
            surf = skia.Surface(160, 160)
            shape.draw(surf.getCanvas())

    def test_each_kind_draws(self):
        specs = [
            lambda c: c.dissolve_out(0.4),
            lambda c: c.dissolve_out(0.4, style="vortex"),
            lambda c: c.dissolve_out(0.4, style="wipe"),
            lambda c: c.dissolve_in(0.4),
            lambda c: c.dissolve_in(0.4, style="vortex"),
            lambda c: c.fade_in(0.3),
            lambda c: c.fade_out(0.3),
            lambda c: c.implode(0.3),
            lambda c: c.burn_out(0.5),
            lambda c: c.flash(0.2),
            lambda c: c.blink(0.3),
            lambda c: c.pulse_outline(duration=0.3),
            lambda c: c.pop(duration=0.25),
            lambda c: c.knock(distance=12, angle=45),
            lambda c: c.spark_burst(duration=0.35, amount=1.0),
        ]
        for i, apply in enumerate(specs):
            with self.subTest(i=i):
                c = Circle(center=(40 + i * 5, 40), radius=14).set_color("orange")
                apply(c)
                self._draw_ok(c)

    def test_with_visual_and_filter(self):
        c = Circle(center=(60, 60), radius=18).set_color("cyan")
        c.visual = Neon("cyan")
        c.fill_filter = GlowFilter()
        c.dissolve_out(0.4)
        c.pulse_outline()
        self._draw_ok(c)

    def test_dissolve_restores_fill_filter(self):
        """Exit draw strips GlowFilter only for the paint pass; sticky filter remains."""
        glow = GlowFilter()
        c = Circle(center=(60, 60), radius=16).set_color("cyan")
        c.fill_filter = glow
        c.dissolve_out(0.5)
        c._tx_state.life.t0 = self.now()
        self.advance(0.2)
        self.assertIs(c.fill_filter, glow)
        surf = skia.Surface(160, 160)
        c.draw(surf.getCanvas())
        self.assertIs(c.fill_filter, glow)

    def test_fade_strips_filters_for_alpha_layer(self):
        """Fade alpha layer must not drag GlowFilter’s light plate across the bg."""
        glow = GlowFilter()
        c = Circle(center=(60, 60), radius=16).set_color("cyan")
        c.fill_filter = glow
        c.fade_out(0.5)
        c._tx_state.life.t0 = self.now()
        self.advance(0.25)
        mods = tx.compose_draw_mods(c, self.now())
        self.assertIsNotNone(mods)
        self.assertTrue(tx._should_strip_filters(mods))
        self.assertIs(c.fill_filter, glow)
        self._draw_ok(c)
        self.assertIs(c.fill_filter, glow)

        c2 = Circle(center=(80, 80), radius=14).set_color("gold")
        c2.fill_filter = glow
        c2.fade_in(0.5)
        c2._tx_state.life.t0 = self.now()
        self.advance(0.0)
        mods2 = tx.compose_draw_mods(c2, self.now())
        self.assertIsNotNone(mods2)
        self.assertTrue(tx._should_strip_filters(mods2))
        self._draw_ok(c2)
        self.assertIs(c2.fill_filter, glow)

    def test_progress_monotonic(self):
        c = Circle(center=(50, 50), radius=10)
        c.dissolve_out(1.0)
        c._tx_state.life.t0 = self.now()
        p0 = c._tx_state.life.progress(self.now())
        self.advance(0.3)
        p1 = c._tx_state.life.progress(self.now())
        self.advance(0.3)
        p2 = c._tx_state.life.progress(self.now())
        self.assertLessEqual(p0, p1)
        self.assertLessEqual(p1, p2)


class TestEdgeCases(TransientTestBase):
    def test_duration_clamped(self):
        c = Circle(center=(10, 10), radius=5)
        c.dissolve_out(duration=-1)
        self.assertGreaterEqual(c._tx_state.life.duration, 0.05)
        c.flash(duration=0)
        self.assertGreaterEqual(c._tx_state.flash.duration, 0.05)

    def test_duration_non_numeric_raises(self):
        c = Circle(center=(10, 10), radius=5)
        with self.assertRaises(TypeError):
            c.dissolve_out(duration="fast")
        with self.assertRaises(TypeError):
            c.flash(on_done="done")

    def test_invalid_dissolve_style(self):
        c = Circle(center=(10, 10), radius=5)
        with self.assertRaises(ValueError):
            c.dissolve_out(0.2, style="melt")

    def test_duration_is_first_positional(self):
        c = Circle(center=(10, 10), radius=5)
        c.pop(0.5)
        self.assertAlmostEqual(c._tx_state.pop.duration, 0.5)
        self.assertAlmostEqual(c._tx_state.pop.peak, 1.2)
        c.pulse_outline(0.4)
        self.assertAlmostEqual(c._tx_state.pulse.duration, 0.4)
        c.spark_burst(0.3)
        self.assertAlmostEqual(c._tx_state.spark.duration, 0.3)
        c.flash(0.2)
        self.assertAlmostEqual(c._tx_state.flash.duration, 0.2)

    def test_look_params_are_keyword_only(self):
        c = Circle(center=(10, 10), radius=5)
        with self.assertRaises(TypeError):
            c.pop(0.18, 1.4)
        with self.assertRaises(TypeError):
            c.pulse_outline(0.25, "red")
        with self.assertRaises(TypeError):
            c.flash(0.12, 0.5)
        with self.assertRaises(TypeError):
            c.spark_burst(0.35, 1.2)
        with self.assertRaises(TypeError):
            c.fade_out(0.3, lambda s: None)
        c.pop(0.2, scale=1.5)
        self.assertAlmostEqual(c._tx_state.pop.duration, 0.2)
        self.assertAlmostEqual(c._tx_state.pop.peak, 1.5)

    def test_line_pop_no_crash(self):
        ln = Line(p1=(10, 10), p2=(80, 40)).set_color("white")
        ln.line_width = 3
        ln.pop(scale=1.3)
        ln._tx_state.pop.t0 = self.now()
        self.advance(0.05)
        surf = skia.Surface(128, 128)
        ln.draw(surf.getCanvas())
        mods = tx.compose_draw_mods(ln, self.now())
        self.assertIsNotNone(mods)
        self.assertGreater(mods.scale_mul, 1.0)

    def test_multiple_shapes_independent(self):
        a = Circle(center=(20, 20), radius=8)
        b = Circle(center=(90, 90), radius=8)
        a.flash(0.2)
        b.dissolve_out(0.2)
        a._tx_state.flash.t0 = self.now()
        b._tx_state.life.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertFalse(tx.has_active_transient(a))
        self.assertFalse(b.visible)

    def test_second_flash_replaces(self):
        c = Circle(center=(40, 40), radius=10)
        c.flash(duration=1.0, intensity=1.0)
        first = c._tx_state.flash
        c.flash(duration=1.0, intensity=0.5)
        self.assertIsNot(c._tx_state.flash, first)
        self.assertAlmostEqual(c._tx_state.flash.intensity, 0.5)

    def test_destroy_while_active_no_tick_crash(self):
        c = Circle(center=(40, 40), radius=10)
        c.dissolve_out(1.0)
        self.assertTrue(tx.is_registered(c))
        self.assertTrue(c.is_alive)
        c.destroy()
        self.assertFalse(c.is_alive)
        # may still be in weak set until GC, but tick must not crash
        tx.tick_all_transients(self.now())
        self.assertFalse(tx.is_registered(c))

    def test_destroy_cancels_pending_on_done(self):
        """Hard destroy clears other channels without calling their on_done."""
        blink_done = []
        flash_done = []
        c = Circle(center=(40, 40), radius=12)
        c.blink(1.0, on_done=lambda s: blink_done.append("old"))
        c.flash(1.0, on_done=lambda s: flash_done.append(1))  # replaces blink → cancelled
        self.assertEqual(blink_done, ["old"])
        blink_done.clear()
        # reinstall blink for the multi-channel scenario
        c.blink(1.0, on_done=lambda s: blink_done.append(1))
        c.dissolve_out(0.1, on_done=lambda s: s.destroy())
        c._tx_state.life.t0 = self.now()
        c._tx_state.flash.t0 = self.now()
        self.advance(0.5)
        tx.tick_all_transients(self.now())
        self.assertFalse(c.is_alive)
        self.assertEqual(blink_done, [])  # canceled silently by destroy
        self.assertFalse(tx.is_registered(c))

    def test_direct_exclude_cancels_flash_on_done(self):
        done = []
        c = Circle(center=(30, 30), radius=10)
        c.flash(1.0, on_done=lambda s: done.append(1))
        self.assertTrue(tx.is_registered(c))
        c.destroy()
        self.assertFalse(c.is_alive)
        self.assertEqual(done, [])
        self.advance(2.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, [])

    def test_hide_only_keeps_is_alive_and_flash_on_done(self):
        """Exit hide without destroy still runs stacked hit on_done."""
        done = []
        c = Circle(center=(40, 40), radius=10)
        c.flash(0.15, on_done=lambda s: done.append("flash"))
        c.dissolve_out(0.1)  # hide only
        c._tx_state.life.t0 = self.now()
        c._tx_state.flash.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertTrue(c.is_alive)
        self.assertFalse(c.visible)
        self.assertEqual(done, ["flash"])

    def test_undraw_does_not_destroy(self):
        c = Circle(center=(40, 40), radius=10)
        c.flash(1.0)
        c.undraw()
        self.assertTrue(c.is_alive)
        self.assertTrue(tx.is_registered(c))
        self.assertIsNone(c.layer)

    def test_empty_tick_idempotent(self):
        tx.tick_all_transients(self.now())
        tx.tick_all_transients(self.now())
        self.assertEqual(tx.registered_count(), 0)

    def test_tick_all_public(self):
        self.assertTrue(callable(tx.tick_all_transients))

    def test_hidden_still_finishes(self):
        done = []
        c = Circle(center=(40, 40), radius=10)
        c.dissolve_out(0.1, on_done=lambda s: done.append(1))
        c._tx_state.life.t0 = self.now()
        c.visible = False
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, [1])


class TestSparkBurst(TransientTestBase):
    def test_installs_spark_channel(self):
        c = Circle(center=(50, 50), radius=15).set_color("white")
        c.spark_burst(duration=0.4, amount=1.2)
        st = c._tx_state
        self.assertIsNotNone(st.spark)
        self.assertEqual(st.spark.kind, "spark")
        self.assertFalse(st.spark.hide_on_finish)

    def test_spark_named_color(self):
        from scena.transients import SparkBurst
        from scena.color import Color
        sp = SparkBurst(color="white")
        self.assertEqual(sp.color[:3], (1.0, 1.0, 1.0))
        sp2 = SparkBurst(color=Color("gold"))
        expected = (
            float(Color("gold").rgb[0]),
            float(Color("gold").rgb[1]),
            float(Color("gold").rgb[2]),
            1.0,
        )
        self.assertEqual(sp2.color, expected)

    def test_stacks_with_flash(self):
        c = Circle(center=(50, 50), radius=15).set_color("white")
        c.flash(0.2)
        c.spark_burst(0.3)
        self.assertIsNotNone(c._tx_state.flash)
        self.assertIsNotNone(c._tx_state.spark)

    def test_does_not_hide(self):
        c = Circle(center=(50, 50), radius=15).set_color("cyan")
        c.spark_burst(duration=0.15)
        c._tx_state.spark.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertTrue(c.visible)
        self.assertFalse(tx.has_active_transient(c))

    def test_clear_clears_spark(self):
        c = Circle(center=(50, 50), radius=12)
        c.spark_burst()
        self.assertTrue(tx.has_active_transient(c))
        c.clear_transients()
        self.assertFalse(tx.has_active_transient(c))

    def test_replace_same_channel(self):
        c = Circle(center=(40, 40), radius=10)
        c.spark_burst(duration=1.0, amount=0.5)
        first = c._tx_state.spark
        c.spark_burst(duration=1.0, amount=1.5)
        self.assertIsNot(c._tx_state.spark, first)
        self.assertAlmostEqual(c._tx_state.spark.amount, 1.5)


class TestShapeKinds(TransientTestBase):
    def test_various_shapes_dissolve(self):
        shapes = [
            Circle(center=(40, 40), radius=12),
            Rect(center=(100, 40), width=30, height=20),
            Ellipse(center=(160, 40), width=40, height=20),
            RegularPolygon(n=5, center=(220, 40), radius=16),
        ]
        _ln = Line(p1=(20, 100), p2=(100, 140))
        _ln.line_width = 2
        shapes.append(_ln)
        for s in shapes:
            with self.subTest(type=type(s).__name__):
                s.set_color("lime")
                s.dissolve_out(0.3)
                s._tx_state.life.t0 = self.now()
                surf = skia.Surface(256, 200)
                s.draw(surf.getCanvas())
                self.advance(0.5)
                tx.tick_all_transients(self.now())


class TestShapePivotExtent(TransientTestBase):
    """saveLayer / dig footprint must cover free Polygon, Text, rotated Square.

    Regression: ``shape_pivot`` fell back to r=24 (or length/2 without rotation),
    so fade_in / dissolve_in clipped to a center patch only.
    """

    def test_free_polygon_covers_vertices(self):
        import math
        from scena.shapes import Polygon
        p = Polygon(points=[(50, 50), (350, 50), (200, 280)])
        cx, cy, r = tx.shape_pivot(p)
        for v in p.points:
            dist = math.hypot(float(v.x) - cx, float(v.y) - cy)
            self.assertGreaterEqual(r + 1e-3, dist, msg=f"vertex at dist {dist} > r {r}")

    def test_text_covers_layout_box(self):
        from scena import Text
        lab = Text(text="c²", center=(200, 150), font_size=66)
        lab._refresh_layout()
        cx, cy, r = tx.shape_pivot(lab)
        hw = 0.5 * (lab._x2 - lab._x1)
        hh = 0.5 * (lab._y2 - lab._y1)
        need = (hw * hw + hh * hh) ** 0.5
        self.assertGreaterEqual(r + 1e-3, need)
        self.assertGreater(r, 24.0)  # must not use the old fallback

    def test_rotated_square_covers_corners(self):
        import math
        from scena.shapes import Square
        from scena.canvas import _approx_draw_aabb
        sq = Square(center=(200, 150), length=200, angle=35)
        cx, cy, r = tx.shape_pivot(sq)
        # Circumradius of side length L is (L/2)*√2; AABB half-diagonal matches.
        self.assertGreaterEqual(r + 1e-3, 0.5 * 200 * math.sqrt(2.0) - 1.0)
        box = _approx_draw_aabb(sq)
        self.assertIsNotNone(box)
        minx, miny, maxx, maxy = box
        for x, y in ((minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)):
            self.assertGreaterEqual(r + 1e-3, math.hypot(x - cx, y - cy))

    def test_circle_keeps_true_radius(self):
        c = Circle(center=(50, 50), radius=38)
        _cx, _cy, r = tx.shape_pivot(c)
        self.assertAlmostEqual(r, 38.0, places=5)

    def test_center_radius_matches_shape_pivot(self):
        from scena.recipes import _center_radius
        from scena.shapes import Polygon, Square
        from scena import Text
        shapes = [
            Circle(center=(40, 40), radius=12),
            Polygon(points=[(0, 0), (100, 0), (50, 80)]),
            Square(center=(80, 80), length=60, angle=20),
            Text(text="Hi", center=(100, 100), font_size=48),
        ]
        for s in shapes:
            with self.subTest(type=type(s).__name__):
                self.assertEqual(tx.shape_pivot(s), _center_radius(s))

    def test_fade_in_polygon_ink_outside_old_fallback(self):
        """Mid fade_in must paint vertices beyond the old 24+12 DU layer."""
        import math
        from scena.shapes import Polygon
        p = Polygon(points=[(40, 40), (360, 40), (200, 260)])
        p.set_color((1.0, 0.0, 0.0, 1.0))
        p.fade_in(1.0)
        p._tx_state.life.t0 = self.now()
        self.advance(0.5)
        mods = tx.compose_draw_mods(p, self.now())
        self.assertIsNotNone(mods)
        self.assertGreater(mods.alpha_mul, 0.2)

        surf = skia.Surface(400, 300)
        canvas = surf.getCanvas()
        canvas.clear(skia.ColorBLACK)
        # Scena y-up vs Skia y-down: draw via envelope in raw coords is enough
        # to prove the saveLayer is not clipped to the old 24 DU radius.
        tx.draw_with_transients(p, canvas, mods)
        img = surf.makeImageSnapshot()
        info = skia.ImageInfo.MakeN32Premul(400, 300)
        buf = bytearray(400 * 300 * 4)
        ok = img.readPixels(info, buf, 400 * 4, 0, 0)
        self.assertTrue(ok)
        # Pixel (50, 50) is near first vertex; old layer was ~center±36 only.
        cx, cy, _r = tx.shape_pivot(p)
        self.assertGreater(math.hypot(50 - cx, 50 - cy), 40.0)
        i = (50 * 400 + 50) * 4
        # Premul RGBA — any non-black channel means the vertex was not clipped.
        self.assertGreater(buf[i] + buf[i + 1] + buf[i + 2], 0)

    def test_layer_bounds_cover_polygon_aabb(self):
        from scena.shapes import Polygon
        from scena.canvas import _approx_draw_aabb
        p = Polygon(points=[(50, 50), (350, 50), (200, 280)])
        p.fade_in(1.0)
        p._tx_state.life.t0 = self.now()
        mods = tx.compose_draw_mods(p, self.now())
        cx, cy, half = tx.shape_pivot(p)
        bounds = tx._transient_layer_bounds(p, cx, cy, half, mods)
        box = _approx_draw_aabb(p)
        self.assertIsNotNone(box)
        minx, miny, maxx, maxy = box
        self.assertLessEqual(bounds.left(), minx)
        self.assertLessEqual(bounds.top(), miny)
        self.assertGreaterEqual(bounds.right(), maxx)
        self.assertGreaterEqual(bounds.bottom(), maxy)
        # Far larger than the historic 24+12 fallback square.
        self.assertGreater(bounds.width(), 80.0)
        self.assertGreater(bounds.height(), 80.0)


class TestEnterAndMotion(TransientTestBase):
    def test_dissolve_in_shows_and_stays(self):
        done = []
        c = Circle(center=(40, 40), radius=12)
        c.visible = False
        c.dissolve_in(0.2, on_done=lambda s: done.append(1))
        self.assertTrue(c.visible)
        c._tx_state.life.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertTrue(c.visible)
        self.assertEqual(done, [1])

    def test_fade_in_alpha_progress(self):
        c = Circle(center=(40, 40), radius=10)
        c.fade_in(1.0)
        c._tx_state.life.t0 = self.now()
        self.advance(0.0)
        mods0 = tx.compose_draw_mods(c, self.now())
        self.advance(0.5)
        mods1 = tx.compose_draw_mods(c, self.now())
        self.assertIsNotNone(mods0)
        self.assertIsNotNone(mods1)
        self.assertLess(mods0.alpha_mul, mods1.alpha_mul + 1e-9)
        self.assertGreater(mods1.alpha_mul, 0.4)

    def test_implode_hides(self):
        c = Circle(center=(40, 40), radius=10)
        c.implode(0.15)
        c._tx_state.life.t0 = self.now()
        self.advance(1.0)
        tx.tick_all_transients(self.now())
        self.assertFalse(c.visible)

    def test_knock_offset_midway(self):
        c = Circle(center=(50, 50), radius=12)
        c.knock(duration=0.2, distance=20, angle=0)
        c._tx_state.knock.t0 = self.now()
        self.advance(0.05)
        mods = tx.compose_draw_mods(c, self.now())
        self.assertIsNotNone(mods)
        self.assertGreater(abs(mods.offset_x) + abs(mods.offset_y), 1.0)
        # geometry unchanged
        self.assertAlmostEqual(c.center.x, 50.0)

    def test_dissolve_in_dig_decreases(self):
        c = Circle(center=(40, 40), radius=10)
        c.dissolve_in(1.0, style="noise")
        c._tx_state.life.t0 = self.now()
        m0 = tx.compose_draw_mods(c, self.now())
        self.advance(0.5)
        m1 = tx.compose_draw_mods(c, self.now())
        self.assertGreater(m0.dissolve_progress, m1.dissolve_progress)


class TestFlashText(TransientTestBase):
    def tearDown(self):
        super().tearDown()
        for w in list(getattr(self, "_widgets", ())):
            try:
                w.destroy()
            except Exception:
                pass
        self._widgets = []

    def _label(self, **kwargs):
        from scena import Text
        lab = Text(top_left=(10, 40), font_size=16, **kwargs)
        self._widgets = getattr(self, "_widgets", [])
        self._widgets.append(lab)
        return lab

    def test_override_then_resume_linked_value(self):
        from scena import st
        st.create("hud", initial="HP 5")
        lab = self._label(text="idle")
        lab["text"] @= st["hud"]
        self.assertEqual(lab._displayed_text(), "HP 5")

        lab.flash_text("HIT!", duration=0.5)
        lab._tx_state.text.t0 = self.now()
        self.assertEqual(lab._displayed_text(), "HIT!")
        self.assertEqual(lab.value, "HP 5")  # cell unchanged

        self.advance(0.6)
        tx.tick_all_transients(self.now())
        self.assertEqual(lab._displayed_text(), "HP 5")
        self.assertEqual(lab.value, "HP 5")
        st.hud = "HP 3"
        self.assertEqual(lab._displayed_text(), "HP 3")

    def test_flash_text_on_done(self):
        done = []
        lab = self._label(text="ready")
        lab.flash_text("GO", duration=0.2, on_done=lambda w: done.append(1))
        lab._tx_state.text.t0 = self.now()
        self.advance(0.3)
        tx.tick_all_transients(self.now())
        self.assertEqual(done, [1])
        self.assertEqual(lab._displayed_text(), "ready")


class TestDissolveMaskScale(unittest.TestCase):
    def test_pop_plus_dissolve_does_not_square_the_mask(self):
        from unittest import mock
        c = Circle(center=(40, 40), radius=10)
        mods = tx.DrawMods(
            scale_mul=2.0,
            dissolve_progress=0.4,
            dissolve_seed=1.0,
        )
        surf = skia.Surface(120, 120)
        with mock.patch.object(tx, "_apply_dissolve_mask") as mask:
            tx.draw_with_transients(c, surf.getCanvas(), mods)
        half = mask.call_args.args[6]
        _cx, _cy, pivot = tx.shape_pivot(c)
        self.assertAlmostEqual(half, pivot)


if __name__ == "__main__":
    unittest.main()
