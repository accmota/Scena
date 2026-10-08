"""
Registry / layer / group tests: registration, soft vs hard removal, layer z-order,
``canvas.layers`` facade, live ``group["name"]``, and id lookup.

These target real regressions (stale groups, ``layer=None`` undrawn, soft clear
calling ``clean_up``, broken reset).

Run headless:

    python -m unittest tests.test_registry_layers -v
"""

import os
import subprocess
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.source_support import iter_files

from scena import Text, above, below, canvas, group, init
from scena.canvas import ScenaCanvas
from scena.registry import (
    BUILT_IN_LAYERS,
    layer_is_parallax,
    normalize_layer_name,
)
from scena.shapes import Circle, Line, Point, Polygon, Rect
from scena.state import Attribute, get_scena_system


def _registry():
    return ScenaCanvas.get_current().registry


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        self._owned = []

    def tearDown(self):
        for s in list(self._owned):
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()
        _registry().clear_group_formulas()
        for name in list(canvas.layers):
            if name not in BUILT_IN_LAYERS:
                try:
                    canvas.layers[name].delete(destroy_shapes=True)
                except Exception:
                    pass
        canvas.layers.default = 'default'

    def track(self, shape):
        self._owned.append(shape)
        return shape


class TestEqualZDrawsInCreationOrder(RegistryTestCase):
    """Guia layers.create (PM13): below= / above= is the target's z -/+ 1, so
    two layers made below the same one share a z; equal z draws in creation
    order (the newer on top)."""

    def test_tie(self):
        a = canvas.layers.create("pm13_a", below="default")
        b = canvas.layers.create("pm13_b", below="default")
        self.assertEqual(a.z, b.z)
        names = [n for n in canvas.layers if n in ("pm13_a", "pm13_b")]
        self.assertEqual(names, ["pm13_a", "pm13_b"])       # drawn first = behind


class TestEmptyGroupVerbsBuildNothing(RegistryTestCase):
    """Bug PM7: a verb on an empty group built a full Blank Shape per call
    (~0.3 ms, paid every frame by ``group["tiros"].move_by(...)`` while no
    shot is alive) and left it in the live roster until GC. Guia "Agir em
    massa": the method does nothing and returns neither the group nor a list
    (None); with ``time=`` a Handle; an unknown name still raises."""

    def _count_blanks(self):
        from unittest import mock
        from scena.shapes import Blank
        made = []
        real = Blank.__init__

        def spy(obj, *a, **k):
            made.append(obj)
            return real(obj, *a, **k)
        return made, mock.patch.object(Blank, "__init__", spy)

    def test_a_verb_builds_nothing_and_returns_none(self):
        from scena import group
        made, patch = self._count_blanks()
        n0 = len(_registry().live)
        with patch:
            for _ in range(5):
                self.assertIsNone(group["pm7_empty"].move_by(1, 2))
                self.assertIsNone(group["pm7_empty"].rotate_by(10))
                group["pm7_empty"].visual = None
        self.assertEqual(made, [])
        self.assertEqual(len(_registry().live), n0)

    def test_timed_verb_still_returns_a_handle_and_typos_still_raise(self):
        from scena import group
        from scena.process import Handle
        h = group["pm7_empty"].move_by(1, 0, time=0.2)
        self.assertIsInstance(h, Handle)
        h.cancel()
        with self.assertRaises(AttributeError):
            group["pm7_empty"].mvoe_by(1, 0)
        with self.assertRaises(AttributeError):
            group["pm7_empty"].hp


class TestNormalizeLayerName(RegistryTestCase):
    def test_none_and_blank(self):
        self.assertIsNone(normalize_layer_name(None))
        self.assertIsNone(normalize_layer_name(''))
        self.assertIsNone(normalize_layer_name('   '))

    def test_keeps_real_names(self):
        self.assertEqual(normalize_layer_name('default'), 'default')
        self.assertEqual(normalize_layer_name('top'), 'top')

    def test_none_string_is_not_special(self):
        # 'none' is not a sentinel; unknown layer names fail at register time.
        self.assertEqual(normalize_layer_name('none'), 'none')

    def test_int_passthrough(self):
        self.assertEqual(normalize_layer_name(10), 10)
        self.assertEqual(normalize_layer_name(-1), -1)
        self.assertEqual(normalize_layer_name(0), 0)

    def test_bool_rejected(self):
        with self.assertRaises(TypeError):
            normalize_layer_name(True)
        with self.assertRaises(TypeError):
            normalize_layer_name(False)


class TestRegistration(RegistryTestCase):
    def test_circle_defaults_to_default_layer(self):
        c = self.track(Circle(center=(10, 10), radius=5))
        self.assertEqual(c.layer, 'default')
        self.assertIn(c, _registry().layers['default']._objects)
        self.assertTrue(_registry().is_live(c))

    def test_point_default_not_drawn(self):
        p = self.track(Point(1, 2))
        self.assertIsNone(p.layer)
        self.assertNotIn(p, _registry().layers['default']._objects)
        self.assertTrue(_registry().is_live(p))

    def test_explicit_none_not_drawn(self):
        c = self.track(Circle(center=(0, 0), radius=3, layer=None))
        self.assertIsNone(c.layer)
        self.assertNotIn(c, _registry().layers['default']._objects)
        for layer in _registry().layers.values():
            self.assertNotIn(c, layer._objects)

    def test_top_layer(self):
        c = self.track(Circle(center=(0, 0), radius=3, layer='top'))
        self.assertEqual(c.layer, 'top')
        self.assertIn(c, _registry().layers['top']._objects)

    def test_same_group_twice_is_fine(self):
        # Formerly a duplicate id raised; a tag names any number of actors.
        a = self.track(Circle(center=(0, 0), radius=1, group='dup'))
        b = self.track(Circle(center=(1, 1), radius=1, group='dup'))
        self.assertEqual(list(group['dup']), [a, b])

    def test_unknown_layer_raises(self):
        with self.assertRaises(ValueError):
            self.track(Circle(center=(0, 0), radius=1, layer='nope'))

    def test_no_builtin_no_draw(self):
        self.assertNotIn('no_draw', canvas.layers)
        self.assertEqual(set(BUILT_IN_LAYERS), {'top', 'default', 'ui'})


class TestLayerNoneSetter(RegistryTestCase):
    def test_assign_none(self):
        c = self.track(Circle(center=(0, 0), radius=2))
        self.assertEqual(c.layer, 'default')
        c.layer = None
        self.assertIsNone(c.layer)
        self.assertNotIn(c, _registry().layers['default']._objects)

    def test_reassign_after_none(self):
        c = self.track(Circle(center=(0, 0), radius=2))
        c.layer = None
        c.layer = 'top'
        self.assertEqual(c.layer, 'top')
        self.assertIn(c, _registry().layers['top']._objects)


class TestSoftVsHardRemoval(RegistryTestCase):
    def test_undraw_keeps_roster_and_graph(self):
        c = self.track(Circle(center=(50, 50), radius=10))
        dep = Attribute(0.0)
        dep @= lambda: c.radius
        get_scena_system().flush()
        self.assertAlmostEqual(dep.value, 10.0)

        c.undraw()
        self.assertIsNone(c.layer)
        self.assertTrue(_registry().is_live(c))
        c.radius = 20
        get_scena_system().flush()
        self.assertAlmostEqual(dep.value, 20.0)

    def test_destroy_leaves_roster(self):
        c = Circle(center=(0, 0), radius=1)
        c.destroy()
        self.assertFalse(_registry().is_live(c))

    def test_destroy_leaves_its_groups_at_once(self):
        # Guia #grp-entrar (PM1): a destroyed object leaves its groups at once,
        # also inside a frame batch (an on_click that destroys then respawns).
        from scena import group
        ss = get_scena_system()
        a = self.track(Circle(center=(0, 0), radius=1, group="pm1_g"))
        b = self.track(Circle(center=(5, 0), radius=1, group="pm1_g"))
        ss.begin_frame_batch()
        try:
            group["pm1_g"].destroy()
            self.assertEqual(len(group["pm1_g"]), 0)
            c = self.track(Circle(center=(9, 0), radius=1, group="pm1_g"))
            self.assertEqual(list(group["pm1_g"]), [c])
        finally:
            ss.end_frame_batch()
        self.assertFalse(a.is_alive or b.is_alive)

    def test_soft_clear_does_not_cleanup(self):
        c = self.track(Circle(center=(0, 0), radius=4))
        canvas.layers['default'].clear(hard=False)
        self.assertIsNone(c.layer)
        self.assertTrue(_registry().is_live(c))
        c.layer = 'default'
        self.assertIn(c, _registry().layers['default']._objects)

    def test_hard_clear_destroys(self):
        c = Circle(center=(0, 0), radius=4)
        canvas.layers['default'].clear(hard=True)
        self.assertFalse(_registry().is_live(c))


class TestZOrderAndInteractive(RegistryTestCase):
    def test_builtin_z_order(self):
        info = {row['name']: row for row in canvas.layers.list()}
        self.assertLess(info['default']['z'], info['top']['z'])
        self.assertLess(info['top']['z'], info['ui']['z'])
        self.assertEqual(set(info), {'default', 'top', 'ui'})

    def test_draw_order_low_z_first(self):
        # Camera walk skips ``ui`` (view pass with widgets).
        names = [layer.name for layer in _registry().layers.iter_draw_order()]
        self.assertEqual(names, ['default', 'top'])
        self.assertNotIn('ui', names)

    def test_hit_order_high_z_first(self):
        names = [layer.name for layer in _registry().layers.iter_hit_order()]
        self.assertEqual(names, ['top', 'default'])
        self.assertNotIn('ui', names)

    def test_move_to_front_within_layer(self):
        a = self.track(Circle(center=(0, 0), radius=1))
        b = self.track(Circle(center=(1, 0), radius=1))
        objs = _registry().layers['default']._objects
        self.assertLess(objs.index(a), objs.index(b))
        a.move_to_front()
        self.assertEqual(objs[-1], a)

    def test_interactive_follows_layer_change(self):
        c = self.track(Circle(center=(0, 0), radius=5))
        c.clickable = True
        self.assertIn(c, _registry().layers['default']._interactive)
        c.layer = 'top'
        self.assertNotIn(c, _registry().layers['default']._interactive)
        self.assertIn(c, _registry().layers['top']._interactive)
        c.layer = None
        self.assertNotIn(c, _registry().layers['top']._interactive)
        hit = list(_registry().iter_interactive_hit_order())
        self.assertNotIn(c, hit)


class TestLayersFacade(RegistryTestCase):
    def test_create_above_and_using(self):
        canvas.layers.create('guides', above='default')
        info = {row['name']: row for row in canvas.layers.list()}
        self.assertGreater(info['guides']['z'], info['default']['z'])
        self.assertLess(info['guides']['z'], info['top']['z'])

        with canvas.layers.using('guides'):
            c = self.track(Circle(center=(0, 0), radius=1))
        self.assertEqual(c.layer, 'guides')
        self.assertEqual(canvas.layers.default, 'default')

    def test_cannot_delete_builtin(self):
        with self.assertRaises(ValueError):
            canvas.layers['default'].delete()
        with self.assertRaises(ValueError):
            canvas.layers['top'].delete()

    def test_delete_custom_destroys_shapes(self):
        canvas.layers.create('tmp', z=5)
        c = Circle(center=(0, 0), radius=1, layer='tmp')
        canvas.layers['tmp'].delete(destroy_shapes=True)
        self.assertNotIn('tmp', canvas.layers)
        self.assertFalse(_registry().is_live(c))

    def test_delete_survives_on_destroy_spawning_replacement(self):
        # Regression: `destroy_all()` snapshotted the layer's object list
        # once, so an `on_destroy` handler that spawned a new object onto
        # the very layer being cleared left that spawn behind. `Layer.delete`
        # then found a non-empty layer and raised "still has objects" —
        # even though the caller asked to destroy everything first.
        canvas.layers.create('spawner', z=6)

        def _respawn(_evt=None):
            Circle(center=(0, 0), radius=1, layer='spawner', group='spawned')

        c = Circle(center=(0, 0), radius=1, layer='spawner', group='spawned')
        c.on_destroy = _respawn

        canvas.layers['spawner'].delete(destroy_shapes=True)

        self.assertNotIn('spawner', canvas.layers)
        self.assertEqual(group['spawned'].count, 0)

    def test_reset_layers_destroys_on_destroy_spawned_replacement(self):
        # Regression: `reset_layers()` -> `destroy_all()` then wipes
        # `self.layers` outright (`reset_builtins`), so an on_destroy spawn
        # that survived the single-pass sweep became a silent orphan: still
        # alive/registered, but on a layer that no longer exists — never
        # drawn or hit-tested again.
        def _respawn(_evt=None):
            Circle(center=(0, 0), radius=1, group='spawned2')  # -> 'default'

        c = Circle(center=(0, 0), radius=1, group='spawned2')
        c.on_destroy = _respawn

        _registry().reset_layers()

        self.assertEqual(group['spawned2'].count, 0)
        self.assertIn('default', canvas.layers)

    def test_visible_toggle(self):
        canvas.layers.create('off', z=-5)
        canvas.layers['off'].visible = False
        self.assertFalse(_registry().layers['off'].visible)
        drawn = [layer.name for layer in _registry().layers.iter_draw_order()]
        self.assertNotIn('off', drawn)

    def test_name_is_read_only(self):
        # Regression: `l.name = "zz"` used to succeed silently while
        # canvas.layers kept the old key ("zz" not in layers, "far" still in).
        layer = canvas.layers.create('far')
        with self.assertRaises(AttributeError) as cm:
            layer.name = 'zz'
        msg = str(cm.exception)
        self.assertIn('read-only', msg)
        self.assertIn("canvas.layers.create('zz'", msg)
        self.assertIn("shape.layer = 'zz'", msg)
        self.assertEqual(layer.name, 'far')
        self.assertIn('far', canvas.layers)
        self.assertNotIn('zz', canvas.layers)
        self.assertIs(canvas.layers['far'], layer)

    def test_name_write_rejected_on_every_layer_kind(self):
        # Bug class: any layer whose .name could drift from its registry key.
        # Covers custom named, built-ins, and numeric (identity = z) layers.
        c = self.track(Circle(center=(0, 0), radius=5, layer=7))
        canvas.layers.create('named')
        for key in ('named', 'default', 'top', 'ui', 7):
            layer = canvas.layers[key]
            with self.subTest(key=key):
                with self.assertRaises(AttributeError):
                    layer.name = 'renamed'
                self.assertEqual(layer.name, key)
                self.assertIs(canvas.layers[key], layer)
        self.assertNotIn('renamed', canvas.layers)
        self.assertEqual(c.layer, 7)

    def test_name_write_keeps_members_in_sync(self):
        layer = canvas.layers.create('far')
        c = self.track(Circle(center=(0, 0), radius=5, layer='far'))
        with self.assertRaises(AttributeError):
            layer.name = 'zz'
        self.assertEqual(c.layer, 'far')
        self.assertEqual(layer._live_count, 1)
        info = {d['name']: d for d in canvas.layers.list()}
        self.assertEqual(info['far']['object_count'], 1)

    def test_set_z_reorders(self):
        canvas.layers.create('mid', z=50)
        canvas.layers['mid'].z = 100  # max author z; still below top
        hit = [layer.name for layer in _registry().layers.iter_hit_order()]
        self.assertEqual(hit[0], 'top')
        self.assertEqual(hit[1], 'mid')

    def test_create_rejects_duplicate_z_args(self):
        with self.assertRaises(ValueError):
            canvas.layers.create('bad', z=1, above='default')
        with self.assertRaises(ValueError):
            canvas.layers.create('bad2', above='default', below='top')

    def test_top_z_is_fixed(self):
        from scena.registry import TOP_Z, MAX_LAYER_Z
        self.assertEqual(TOP_Z, 101)
        self.assertEqual(MAX_LAYER_Z, 100)
        self.assertEqual(_registry().layers['top'].z, TOP_Z)
        with self.assertRaises(ValueError):
            canvas.layers['top'].z = 50
        with self.assertRaises(ValueError):
            canvas.layers['top'].z = TOP_Z  # even "same" value
        with self.assertRaises(ValueError):
            canvas.layers.create('above_top', above='top')
        with self.assertRaises(ValueError):
            canvas.layers.create('too_high', z=101)
        with self.assertRaises(ValueError):
            canvas.layers.create('way_high', z=150)

    def test_z_100_allowed_below_top(self):
        canvas.layers.create('near_top', z=100)
        canvas.layers.create('also_near', below='top')
        self.assertEqual(_registry().layers['near_top'].z, 100)
        self.assertEqual(_registry().layers['also_near'].z, 100)
        hit = [layer.name for layer in _registry().layers.iter_hit_order()]
        self.assertEqual(hit[0], 'top')
        self.assertIn('near_top', hit[1:3])
        self.assertIn('also_near', hit[1:3])

    def test_set_z_rejects_at_or_above_top(self):
        canvas.layers.create('low', z=10)
        with self.assertRaises(ValueError):
            canvas.layers['low'].z = 101
        with self.assertRaises(ValueError):
            canvas.layers['low'].z = 200

    def test_set_z_default_up_to_100(self):
        canvas.layers['default'].z = 100
        self.assertEqual(_registry().layers['default'].z, 100)
        with self.assertRaises(ValueError):
            canvas.layers['default'].z = 101
        # restore for other tests / tearDown assumptions
        canvas.layers['default'].z = 0

    def test_create_above_ceiling_rejected(self):
        """above= a z=100 layer would request z=101 → error."""
        canvas.layers.create('ceiling', z=100)
        with self.assertRaises(ValueError):
            canvas.layers.create('overflow', above='ceiling')

    def test_create_below_default(self):
        canvas.layers.create('under', below='default')
        self.assertEqual(_registry().layers['under'].z, -1)
        draw = [layer.name for layer in _registry().layers.iter_draw_order()]
        self.assertEqual(draw[0], 'under')

    def test_create_omit_z_is_zero(self):
        canvas.layers.create('plain')
        self.assertEqual(_registry().layers['plain'].z, 0)

    def test_create_above_default(self):
        canvas.layers.create('guides', above='default')
        self.assertEqual(_registry().layers['guides'].z, 1)

    def test_bool_layer_name_and_z_rejected(self):
        with self.assertRaises(TypeError):
            canvas.layers.create(True)
        layer = canvas.layers['default']
        with self.assertRaises(TypeError):
            layer.z = True
        with self.assertRaises(TypeError):
            canvas.layers.create('typed', z='10')


class TestNumericLayers(RegistryTestCase):
    def test_int_auto_creates_with_matching_z(self):
        c = self.track(Circle(center=(0, 0), radius=1, layer=10))
        self.assertEqual(c.layer, 10)
        self.assertTrue(10 in canvas.layers)
        self.assertEqual(canvas.layers[10].z, 10)
        self.assertIn(c, _registry().layers[10]._objects)

    def test_second_shape_joins_same_layer(self):
        a = self.track(Circle(center=(0, 0), radius=1, layer=10))
        b = self.track(Circle(center=(1, 0), radius=1, layer=10))
        self.assertIs(_registry().layers[10], canvas.layers[10])
        self.assertIn(a, canvas.layers[10]._objects)
        self.assertIn(b, canvas.layers[10]._objects)

    def test_negative_draws_under_default(self):
        c = self.track(Circle(center=(0, 0), radius=1, layer=-1))
        self.assertEqual(c.layer, -1)
        self.assertEqual(canvas.layers[-1].z, -1)
        draw = [layer.name for layer in _registry().layers.iter_draw_order()]
        self.assertLess(draw.index(-1), draw.index('default'))

    def test_bool_rejected(self):
        with self.assertRaises(TypeError):
            Circle(center=(0, 0), radius=1, layer=True)

    def test_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            Circle(center=(0, 0), radius=1, layer=101)

    def test_z_is_frozen(self):
        self.track(Circle(center=(0, 0), radius=1, layer=10))
        with self.assertRaises(ValueError):
            canvas.layers[10].z = 5
        self.assertEqual(canvas.layers[10].z, 10)

    def test_create_rejects_int_name(self):
        with self.assertRaises(TypeError):
            canvas.layers.create(10)

    def test_create_rejects_blank_name(self):
        # An empty/whitespace-only name used to be accepted and stored
        # verbatim; ``normalize_layer_name`` maps blank -> None (undrawn),
        # so the layer could never be targeted by `layer=`.
        with self.assertRaises(ValueError):
            canvas.layers.create("")
        with self.assertRaises(ValueError):
            canvas.layers.create("   ")

    def test_create_strips_padded_name(self):
        # Regression: `create(" hud ")` used to store the raw padded key,
        # but a drawable's `layer=" hud "` (or `layer="hud"`) normalizes via
        # ``normalize_layer_name`` (strips whitespace) — the padded layer
        # was created but could never be found by that lookup.
        canvas.layers.create(" hud ")
        self.assertIn("hud", canvas.layers)
        c = self.track(Circle(center=(0, 0), radius=1, layer="hud"))
        self.assertIs(c.layer, "hud")
        self.assertIn(c, canvas.layers["hud"]._objects)

    def test_separate_namespace_from_string_ten(self):
        self.track(Circle(center=(0, 0), radius=1, layer=10))
        self.assertFalse('10' in canvas.layers)
        canvas.layers.create('10', z=99)
        self.assertEqual(canvas.layers[10].z, 10)
        self.assertEqual(canvas.layers['10'].z, 99)
        self.assertIsNot(canvas.layers[10], canvas.layers['10'])

    def test_setter_auto_vivifies(self):
        c = self.track(Circle(center=(0, 0), radius=1))
        self.assertEqual(c.layer, 'default')
        c.layer = 20
        self.assertEqual(c.layer, 20)
        self.assertTrue(20 in canvas.layers)
        self.assertEqual(canvas.layers[20].z, 20)
        self.assertIn(c, canvas.layers[20]._objects)

    def test_visible_and_delete(self):
        c = self.track(Circle(center=(0, 0), radius=1, layer=10))
        canvas.layers[10].visible = False
        self.assertFalse(_registry().layers[10].visible)
        drawn = [layer.name for layer in _registry().layers.iter_draw_order()]
        self.assertNotIn(10, drawn)
        canvas.layers[10].visible = True
        canvas.layers[10].delete(destroy_shapes=True)
        self.assertNotIn(10, canvas.layers)
        self.assertFalse(_registry().is_live(c))
        self._owned.remove(c)

    def test_numeric_never_parallax_allows_clickable(self):
        c = self.track(Circle(center=(0, 0), radius=1, layer=10))
        self.assertFalse(layer_is_parallax(_registry().layers, 10))
        c.clickable = True  # must not raise ParallaxLayerError
        self.assertTrue(c.clickable)


class TestLayerWriteGuard(RegistryTestCase):
    """Regression: ``Layer`` was a plain dataclass, so ``layer.visable = False``,
    ``layer.scroll = (0, 0)`` or ``layer.pan_response = 0.5`` stored a dead
    attribute and did nothing. The handle is a closed surface now."""

    KINDS = ('named', 'default', 'top', 'ui', 7)

    def _layers(self):
        self.track(Circle(center=(0, 0), radius=5, layer=7))
        canvas.layers.create('named')
        return [(key, canvas.layers[key]) for key in self.KINDS]

    def test_unknown_name_raises_on_every_layer_kind(self):
        for key, layer in self._layers():
            for attr in ('opacity', 'hidden', 'speed', 'xyz'):
                with self.subTest(key=key, attr=attr):
                    with self.assertRaises(AttributeError) as cm:
                        setattr(layer, attr, 1)
                    self.assertIn(repr(attr), str(cm.exception))
                    self.assertIn('Writable on a layer: visible, z, post_fx, scroll.', str(cm.exception))
                    self.assertNotIn(attr, vars(layer))

    def test_typo_suggests_the_real_name(self):
        layer = canvas.layers.create('far')
        for typo, real in (('visable', 'visible'), ('visibel', 'visible'),
                           ('post_xf', 'post_fx'), ('postfx', 'post_fx'),
                           ('nmae', 'name')):
            with self.subTest(typo=typo):
                with self.assertRaises(AttributeError) as cm:
                    setattr(layer, typo, False)
                self.assertIn(f"Did you mean {real!r}?", str(cm.exception))
        self.assertTrue(layer.visible)

    def test_typo_of_a_frozen_knob_carries_the_create_hint(self):
        layer = canvas.layers.create('far')
        with self.assertRaises(AttributeError) as cm:
            layer.pan_respons = 0.5
        msg = str(cm.exception)
        self.assertIn("Did you mean 'pan_response'?", msg)
        self.assertIn('canvas.layers.create(', msg)
        # ``scroll`` is live (P3): its typo names the writable spelling.
        with self.assertRaises(AttributeError) as cm:
            layer.scrol = (0, 0)
        self.assertIn("Did you mean 'scroll'?", str(cm.exception))
        self.assertNotIn('scrol', vars(layer))

    def test_frozen_camera_knobs_raise_with_create_hint(self):
        layer = canvas.layers.create('far', pan_response=0.5, scroll=(10, 0))
        before = layer._response
        for knob, value in (('pan_response', 0.2), ('zoom_response', 0.2),
                            ('rotation_response', 0.0), ('response', None)):
            with self.subTest(knob=knob):
                with self.assertRaises(AttributeError) as cm:
                    setattr(layer, knob, value)
                msg = str(cm.exception)
                self.assertIn('set only in', msg)
                self.assertIn("canvas.layers.create('far',", msg)
                self.assertNotIn(knob, vars(layer))
        self.assertIs(layer._response, before)
        self.assertEqual(layer._response.scroll, (10, 0))

    def test_frozen_knob_on_numeric_layer_points_to_a_named_layer(self):
        self.track(Circle(center=(0, 0), radius=5, layer=7))
        with self.assertRaises(ValueError) as cm:
            canvas.layers[7].scroll = (5, 0)
        msg = str(cm.exception)
        self.assertIn('numeric layers have no camera response', msg)
        self.assertIn("canvas.layers.create('name', scroll=...)", msg)

    def test_method_assignment_raises(self):
        layer = canvas.layers.create('far')
        with self.assertRaises(AttributeError) as cm:
            layer.delete = None
        self.assertIn('is a method', str(cm.exception))
        layer.delete()
        self.assertNotIn('far', canvas.layers)

    def test_author_writes_still_work(self):
        layer = canvas.layers.create('far', z=3)
        layer.visible = False
        self.assertFalse(canvas.layers['far'].visible)
        layer.visible = True
        layer.z = 7
        self.assertEqual(canvas.layers['far'].z, 7)
        canvas.layers['top'].post_fx = False
        self.assertFalse(canvas.layers['top'].post_fx)
        canvas.layers['top'].post_fx = True
        # Setters keep their own checks (not swallowed by the guard).
        with self.assertRaises(ValueError):
            canvas.layers['default'].post_fx = False
        with self.assertRaises(AttributeError) as cm:
            layer.name = 'zz'
        self.assertIn('read-only', str(cm.exception))

    def test_internal_field_writes_still_work(self):
        # Every dataclass field stays writable: the stack, the draw walk
        # (tombstone / compact) and test harnesses write them directly.
        from dataclasses import fields
        from scena.registry import Layer
        layer = canvas.layers.create('far')
        for f in fields(Layer):
            with self.subTest(field=f.name):
                setattr(layer, f.name, getattr(layer, f.name))
        c = self.track(Circle(center=(0, 0), radius=5, layer='far'))
        c.layer = 'default'          # tombstone on 'far'
        self.assertEqual(layer._tombstones, 1)
        layer._compact()
        self.assertEqual(layer._tombstones, 0)
        self.assertEqual(layer._live_count, 0)

    def test_scrolling_layer_lifecycle(self):
        layer = canvas.layers.create('sky', scroll=(20, 0), pan_response=0.5)
        self.assertIsNotNone(layer._scroll_state)
        self.assertIs(layer._stack, _registry().layers)
        self.track(Circle(center=(0, 0), radius=5, layer='sky'))
        layer.clear(hard=True)
        layer.delete()
        self.assertNotIn('sky', canvas.layers)


class TestAboveBelow(RegistryTestCase):
    def test_relative_to_default(self):
        self.assertEqual(below('default'), -1)
        self.assertEqual(above('default'), 1)

    def test_circle_on_below_default(self):
        c = self.track(Circle(center=(0, 0), radius=1, layer=below('default')))
        self.assertEqual(c.layer, -1)
        self.assertEqual(canvas.layers[-1].z, -1)

    def test_missing_anchor_raises(self):
        with self.assertRaises(ValueError):
            below('nope')
        with self.assertRaises(ValueError):
            above('nope')

    def test_numeric_anchor(self):
        self.track(Circle(center=(0, 0), radius=1, layer=10))
        self.assertEqual(above(10), 11)
        self.assertEqual(below(10), 9)

    def test_named_anchor(self):
        canvas.layers.create('hud', z=5)
        self.assertEqual(above('hud'), 6)
        self.assertEqual(below('hud'), 4)

    def test_above_top_raises(self):
        with self.assertRaises(ValueError) as ctx:
            above('top')
        self.assertIn("top", str(ctx.exception))

    def test_below_top(self):
        self.assertEqual(below('top'), 100)


class TestGroupLiveView(RegistryTestCase):
    def test_live_membership(self):
        a = self.track(Circle(center=(0, 0), radius=1, group='g_live'))
        g = group['g_live']
        self.assertTrue(g.is_live)
        self.assertEqual(len(g), 1)
        self.assertIn(a, g)

        b = self.track(Circle(center=(1, 0), radius=1, group='g_live'))
        self.assertEqual(len(g), 2)
        self.assertIn(b, g)

        b.remove_from_group('g_live')
        self.assertEqual(len(g), 1)
        self.assertNotIn(b, g)

    def test_second_call_same_live_contents(self):
        self.track(Circle(center=(0, 0), radius=1, group='g2'))
        g1 = group['g2']
        self.track(Circle(center=(1, 0), radius=1, group='g2'))
        g2 = group['g2']
        self.assertEqual(len(g1), 2)
        self.assertEqual(len(g2), 2)
        self.assertEqual(set(g1), set(g2))

    def test_broadcast_sees_new_members(self):
        a = self.track(Circle(center=(0, 0), radius=1, group='g_bc'))
        g = group['g_bc']
        b = self.track(Circle(center=(10, 0), radius=1, group='g_bc'))
        g.move_by(5, 0)
        self.assertAlmostEqual(float(a.center.x), 5.0, places=5)
        self.assertAlmostEqual(float(b.center.x), 15.0, places=5)

    def test_no_mutable_set_api(self):
        g = group['empty_mut']
        self.assertFalse(hasattr(g, 'add'))
        self.assertFalse(hasattr(g, 'remove'))
        self.assertFalse(hasattr(g, 'refresh'))

    def test_set_algebra_is_snapshot(self):
        self.track(Circle(center=(0, 0), radius=1, group='ga'))
        self.track(Circle(center=(1, 0), radius=1, group='gb'))
        snap = group['ga'] | group['gb']
        self.assertFalse(snap.is_live)
        self.assertEqual(len(snap), 2)
        self.track(Circle(center=(2, 0), radius=1, group='ga'))
        self.assertEqual(len(snap), 2)
        self.assertEqual(len(group['ga']), 2)

    def test_group_constructor_kwarg(self):
        c = self.track(Rect(center=(0, 0), width=10, height=10, group='rects'))
        self.assertIn(c, group['rects'])

    def test_iter_survives_destroy_in_loop(self):
        a = self.track(Circle(center=(0, 0), radius=1, group='g_iter'))
        b = self.track(Circle(center=(1, 0), radius=1, group='g_iter'))
        seen = []
        for obj in group['g_iter']:
            seen.append(obj)
            obj.destroy()
        self.assertEqual(set(seen), {a, b})
        self.assertTrue(group['g_iter'].empty)
        self.assertFalse(a.is_alive)
        self.assertFalse(b.is_alive)

    def test_iter_does_not_see_joiners_mid_loop(self):
        a = self.track(Circle(center=(0, 0), radius=1, group='g_join'))
        seen = []
        for obj in group['g_join']:
            seen.append(obj)
            self.track(Circle(center=(1, 0), radius=1, group='g_join'))
        self.assertEqual(seen, [a])
        self.assertEqual(group['g_join'].count, 2)

    def test_next_iter_sees_joiners(self):
        g = group['g_later']
        self.track(Circle(center=(0, 0), radius=1, group='g_later'))
        self.assertEqual(len(list(g)), 1)
        self.track(Circle(center=(1, 0), radius=1, group='g_later'))
        self.assertEqual(len(list(g)), 2)


class TestGroupHelpers(RegistryTestCase):
    def test_count_and_empty_are_live(self):
        g = group['helpers']
        self.assertTrue(g.empty)
        self.assertEqual(g.count, 0)
        self.assertEqual(len(g), 0)
        a = self.track(Circle(center=(0, 0), radius=1, group='helpers'))
        self.assertFalse(g.empty)
        self.assertEqual(g.count, 1)
        self.track(Circle(center=(1, 0), radius=1, group='helpers'))
        self.assertEqual(g.count, 2)
        a.remove_from_group('helpers')
        self.assertEqual(g.count, 1)
        self.assertFalse(g.empty)

    def test_count_missing_group_is_zero(self):
        self.assertTrue(group['no_such_group'].empty)
        self.assertEqual(group['no_such_group'].count, 0)

    def test_any_all_count_where(self):
        a = self.track(Circle(center=(0, 0), radius=1, group='pred'))
        b = self.track(Circle(center=(1, 0), radius=1, group='pred'))
        a.hp = 1
        b.hp = 4
        g = group['pred']
        self.assertTrue(g.any(lambda c: float(c.hp) > 3))
        self.assertFalse(g.any(lambda c: float(c.hp) > 10))
        self.assertFalse(g.all(lambda c: float(c.hp) > 3))
        self.assertTrue(g.all(lambda c: float(c.hp) >= 1))
        self.assertEqual(g.count_where(lambda c: float(c.hp) > 3), 1)
        self.assertEqual(group['empty_pred'].count_where(lambda c: True), 0)
        self.assertTrue(group['empty_pred'].all(lambda c: False))
        self.assertFalse(group['empty_pred'].any(lambda c: True))

    def test_filter_is_snapshot(self):
        a = self.track(Circle(center=(0, 0), radius=1, group='flt'))
        b = self.track(Circle(center=(1, 0), radius=1, group='flt'))
        a.hp = 0
        b.hp = 2
        snap = group['flt'].filter(lambda c: float(c.hp) <= 0)
        self.assertFalse(snap.is_live)
        self.assertEqual(snap.count, 1)
        self.assertIn(a, snap)
        self.assertNotIn(b, snap)
        c = self.track(Circle(center=(2, 0), radius=1, group='flt'))
        c.hp = 0
        self.assertEqual(snap.count, 1)
        self.assertEqual(group['flt'].count_where(lambda s: float(s.hp) <= 0), 2)

    def test_destroy_and_tag_broadcast(self):
        a = self.track(Circle(center=(0, 0), radius=1, group='bulk'))
        b = self.track(Circle(center=(1, 0), radius=1, group='bulk'))
        group['bulk'].tag('shielded')
        self.assertTrue(a.tagged('shielded'))
        self.assertTrue(b.tagged('shielded'))
        group['bulk'].untag('shielded')
        self.assertFalse(a.tagged('shielded'))
        group['bulk'].filter(lambda c: c is a).destroy()
        self.assertFalse(a.is_alive)
        self.assertTrue(b.is_alive)
        self.assertEqual(group['bulk'].count, 1)

    def test_nearest_centroid_box(self):
        a = self.track(Circle(center=(0, 0), radius=2, group='geo'))
        b = self.track(Circle(center=(10, 0), radius=2, group='geo'))
        g = group['geo']
        self.assertIs(g.nearest((1, 0)), a)
        self.assertIs(g.nearest((9, 0)), b)
        self.assertIs(g.nearest((0, 0), where=lambda c: c is b), b)
        self.assertIs(g.nearest((1, 0), within=5), a)
        self.assertIsNone(g.nearest((1, 0), within=0.5))
        cx, cy = g.centroid
        self.assertAlmostEqual(cx, 5.0, places=5)
        self.assertAlmostEqual(cy, 0.0, places=5)
        b_box = g.box
        self.assertAlmostEqual(b_box.width, 14.0, places=5)
        self.assertAlmostEqual(b_box.height, 4.0, places=5)
        self.assertAlmostEqual(b_box.center.x, 5.0, places=5)
        self.assertAlmostEqual(b_box.center.y, 0.0, places=5)
        self.assertAlmostEqual(b_box.angle, 0.0, places=5)
        self.assertIsNone(group['no_geo'].centroid)
        self.assertIsNone(group['no_geo'].box)
        self.assertIsNone(group['no_geo'].nearest((0, 0)))

    def test_group_box_includes_rotation_and_line(self):
        import math
        rect = self.track(Rect(
            center=(0, 0), width=100, height=20, angle=45, group='rotbox',
        ))
        box = group['rotbox'].box
        hw, hh = 50.0, 10.0
        c = abs(math.cos(math.radians(45)))
        s = abs(math.sin(math.radians(45)))
        self.assertAlmostEqual(box.width, 2 * (hw * c + hh * s), places=4)
        self.assertAlmostEqual(box.height, 2 * (hw * s + hh * c), places=4)
        self.assertAlmostEqual(box.angle, 0.0, places=5)
        rect.destroy()

        line = self.track(Line(p1=(-100, 0), p2=(100, 40), group='lines'))
        lbox = group['lines'].box
        self.assertAlmostEqual(lbox.width, 200.0, places=4)
        self.assertAlmostEqual(lbox.height, 40.0, places=4)
        line.destroy()

    def test_group_box_accounts_for_scale(self):
        # Regression: `_member_aabb` had its own geometry (center/radius/
        # width+height/p1p2) independent of draw/cull's `_approx_draw_aabb`
        # and never looked at `.scale` — `group.box` measured a scaled
        # shape as if scale were 1, so `canvas.frame_to(group.box)` cropped
        # it and `nearest`/`centroid` inherited the same blind spot.
        rect = self.track(Rect(
            center=(50, 50), width=20, height=10, group='scaled_box',
        ))
        rect.scale = 3.0
        box = group['scaled_box'].box
        self.assertAlmostEqual(box.width, 60.0, places=4)
        self.assertAlmostEqual(box.height, 30.0, places=4)
        self.assertAlmostEqual(box.center.x, 50.0, places=4)
        self.assertAlmostEqual(box.center.y, 50.0, places=4)

    def test_group_box_polygon_and_text_not_a_point(self):
        # Regression: Polygon and Text have no `.radius` / `.width` /
        # `.height` / `.p1`+`.p2`, so the old `_member_aabb` fell through
        # to a single point at `.center` — `group.box` (and `frame_to` on
        # it) collapsed to a point instead of the shape's real extent.
        poly = self.track(Polygon(
            points=[(0, 0), (200, 0), (100, 300)], group='poly_box',
        ))
        pbox = group['poly_box'].box
        self.assertGreater(pbox.width, 100.0)
        self.assertGreater(pbox.height, 100.0)

        text = self.track(Text("hello world", center=(300, 300), group='text_box'))
        tbox = group['text_box'].box
        self.assertGreater(tbox.width, 1.0)
        self.assertGreater(tbox.height, 1.0)
        self.assertAlmostEqual(tbox.center.x, 300.0, delta=2.0)
        self.assertAlmostEqual(tbox.center.y, 300.0, delta=2.0)

    def test_group_box_empty_collapsed_multi(self):
        self.assertIsNone(group['empty_box'].box)

        p = self.track(Point(10, 20, group='pt'))
        collapsed = group['pt'].box
        self.assertIsNotNone(collapsed)
        self.assertAlmostEqual(collapsed.width, 0.0, places=5)
        self.assertAlmostEqual(collapsed.height, 0.0, places=5)
        self.assertAlmostEqual(collapsed.center.x, 10.0, places=5)
        self.assertAlmostEqual(collapsed.center.y, 20.0, places=5)
        self.assertAlmostEqual(collapsed.angle, 0.0, places=5)

        self.track(Circle(center=(0, 0), radius=2, group='multi'))
        self.track(Circle(center=(10, 0), radius=2, group='multi'))
        multi = group['multi'].box
        self.assertAlmostEqual(multi.width, 14.0, places=5)
        self.assertAlmostEqual(multi.height, 4.0, places=5)
        self.assertAlmostEqual(multi.center.x, 5.0, places=5)
        self.assertAlmostEqual(multi.center.y, 0.0, places=5)
        self.assertAlmostEqual(multi.angle, 0.0, places=5)

    def test_pred_must_be_callable(self):
        g = group['bad_pred']
        with self.assertRaises(TypeError):
            g.filter(None)
        with self.assertRaises(TypeError):
            g.any("nope")
        with self.assertRaises(TypeError):
            g.nearest((0, 0), where="nope")

    def test_queries_survive_membership_change_in_pred(self):
        gid = 'g_qmut'

        def two():
            return (
                self.track(Circle(center=(0, 0), radius=1, group=gid)),
                self.track(Circle(center=(10, 0), radius=1, group=gid)),
            )

        a, b = two()
        seen = []

        def destroy_pred(obj):
            seen.append(obj)
            obj.destroy()
            return False

        self.assertFalse(group[gid].any(destroy_pred))
        self.assertEqual(set(seen), {a, b})
        self.assertTrue(group[gid].empty)

        a, b = two()
        seen.clear()

        def destroy_true(obj):
            seen.append(obj)
            obj.destroy()
            return True

        self.assertTrue(group[gid].all(destroy_true))
        self.assertEqual(set(seen), {a, b})
        self.assertTrue(group[gid].empty)

        a, b = two()
        self.assertEqual(group[gid].count_where(lambda obj: obj.destroy() or True), 2)
        self.assertTrue(group[gid].empty)

        a, b = two()
        snap = group[gid].filter(lambda obj: obj.destroy() or True)
        self.assertFalse(snap.is_live)
        self.assertEqual(set(snap), {a, b})
        self.assertTrue(group[gid].empty)

        a, b = two()
        hit = group[gid].nearest((0, 0), where=lambda obj: obj.destroy() or True)
        self.assertIn(hit, (a, b))
        self.assertTrue(group[gid].empty)

        a, b = two()
        seen.clear()

        def untag_pred(obj):
            seen.append(obj)
            obj.untag(gid)
            return False

        self.assertFalse(group[gid].any(untag_pred))
        self.assertEqual(set(seen), {a, b})
        self.assertTrue(group[gid].empty)

        a = self.track(Circle(center=(0, 0), radius=1, group='g_qjoin'))
        visits = []

        def spawn_pred(obj):
            visits.append(obj)
            self.track(Circle(center=(1, 0), radius=1, group='g_qjoin'))
            return False

        self.assertFalse(group['g_qjoin'].any(spawn_pred))
        self.assertEqual(visits, [a])
        self.assertEqual(group['g_qjoin'].count, 2)


class TestGroupLookupSpelling(RegistryTestCase):
    def test_call_form_raises_migration_error(self):
        with self.assertRaises(TypeError) as ctx:
            group("x")
        msg = str(ctx.exception)
        self.assertIn("group['x']", msg)
        self.assertIn("brackets", msg)

    def test_bracket_lookup_is_live(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_br"))
        g = group["g_br"]
        self.assertTrue(g.is_live)
        self.assertIn(a, g)
        self.assertIs(g[0], a)

    def test_str_index_only_on_root(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_nest"))
        with self.assertRaises(TypeError) as ctx:
            group["g_nest"]["other"]
        self.assertIn("root", str(ctx.exception))
        self.assertIs(group["g_nest"][0], a)


class TestGroupJoinOrder(RegistryTestCase):
    def test_spawn_order_preserved(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_ord"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_ord"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_ord"))
        for _ in range(5):
            self.assertEqual(list(group["g_ord"]), [a, b, c])

    def test_join_order_stable_across_hash_seed(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = (
            f"import sys; sys.path.insert(0, {repo!r})\n"
            "from scena import Circle, group, init\n"
            "init(width=200, height=200)\n"
            "Circle(center=(0, 0), radius=1, group='g_hash')\n"
            "Circle(center=(1, 0), radius=2, group='g_hash')\n"
            "Circle(center=(2, 0), radius=3, group='g_hash')\n"
            "print(','.join(str(round(o.radius)) for o in group['g_hash']))\n"
        )
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = "random"
        env["PYTHONIOENCODING"] = "utf-8"
        for _ in range(3):
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                encoding="utf-8", errors="replace",
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip().splitlines()[-1], "1,2,3")

    def test_retag_goes_to_end(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_re"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_re"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_re"))
        b.untag("g_re")
        b.tag("g_re")
        self.assertEqual(list(group["g_re"]), [a, c, b])

    def test_destroy_removes_and_indices_hold(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_rm"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_rm"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_rm"))
        b.destroy()
        members = list(group["g_rm"])
        self.assertEqual(members, [a, c])
        for i, obj_i in enumerate(group["g_rm"]):
            self.assertIs(obj_i, members[i])

    def test_union_order_left_then_new_from_right(self):
        a1 = self.track(Circle(center=(0, 0), radius=1, group="ua"))
        a2 = self.track(Circle(center=(1, 0), radius=1, group="ua"))
        b1 = self.track(Circle(center=(2, 0), radius=1, group="ub"))
        # overlap: a1 also in b, joined b after b1
        a1.tag("ub")
        snap = group["ua"] | group["ub"]
        self.assertEqual(list(snap), [a1, a2, b1])

    def test_filter_keeps_source_join_order(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="gf"))
        b = self.track(Circle(center=(1, 0), radius=1, group="gf"))
        c = self.track(Circle(center=(2, 0), radius=1, group="gf"))
        a.hp = 0
        b.hp = 1
        c.hp = 0
        snap = group["gf"].filter(lambda s: float(s.hp) <= 0)
        self.assertEqual(list(snap), [a, c])


class TestGroupIndex(RegistryTestCase):
    def test_join_order_rank_and_round_trip(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_idx"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_idx"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_idx"))
        g = group["g_idx"]
        self.assertEqual(g.index(a), 0)
        self.assertEqual(g.index(b), 1)
        self.assertEqual(g.index(c), 2)
        self.assertIs(g[g.index(b)], b)

    def test_retag_moves_to_end(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_idx_re"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_idx_re"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_idx_re"))
        b.untag("g_idx_re")
        b.tag("g_idx_re")
        g = group["g_idx_re"]
        self.assertEqual(g.index(a), 0)
        self.assertEqual(g.index(c), 1)
        self.assertEqual(g.index(b), 2)

    def test_destroy_closes_the_gap(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_idx_rm"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_idx_rm"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_idx_rm"))
        b.destroy()
        g = group["g_idx_rm"]
        self.assertEqual(g.index(a), 0)
        self.assertEqual(g.index(c), 1)
        with self.assertRaises(ValueError) as ctx:
            g.index(b)
        msg = str(ctx.exception)
        self.assertIn("not in", msg)
        self.assertIn("in group['g_idx_rm']", msg)

    def test_missing_member_raises(self):
        self.track(Circle(center=(0, 0), radius=1, group="g_idx_miss"))
        outsider = self.track(Circle(center=(5, 0), radius=1))
        with self.assertRaises(ValueError) as ctx:
            group["g_idx_miss"].index(outsider)
        self.assertIn("made at", str(ctx.exception))
        self.assertIn("not in group['g_idx_miss']", str(ctx.exception))

    def test_string_is_not_a_member(self):
        # There are no ids: a string in ``in`` / ``index`` is a mistake, said loudly.
        self.track(Circle(center=(0, 0), radius=1, group="g_idx_str"))
        g = group["g_idx_str"]
        for probe in (lambda: "nope" in g, lambda: g.index("nope")):
            with self.assertRaises(TypeError) as ctx:
                probe()
            self.assertIn("no ids", str(ctx.exception))
            self.assertIn("tagged('nope')", str(ctx.exception))

    def test_root_raises(self):
        with self.assertRaises(TypeError) as ctx:
            group.index(object())
        self.assertIn("root group", str(ctx.exception))
        self.assertIn("group['wasp'].index", str(ctx.exception))

    def test_snapshot_and_formula(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_idx_wa"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_idx_wb"))
        snap = group["g_idx_wa"] | group["g_idx_wb"]
        self.assertEqual(snap.index(a), 0)
        self.assertEqual(snap.index(b), 1)
        group["g_idx_en"] @= lambda: group["g_idx_wa"] | group["g_idx_wb"]
        self.assertEqual(group["g_idx_en"].index(b), 1)
        extra = self.track(Circle(center=(2, 0), radius=1, group="g_idx_wa"))
        self.assertEqual(group["g_idx_en"].index(extra), 1)
        self.assertEqual(group["g_idx_en"].index(b), 2)


class TestGroupFirstLast(RegistryTestCase):
    def test_first_last_match_join_order_ends(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_ends"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_ends"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_ends"))
        g = group["g_ends"]
        self.assertIs(g.first, a)
        self.assertIs(g.last, c)
        self.assertIs(g.first, g[0])
        self.assertIs(g.last, g[-1])
        self.assertIs(g[-2], b)

    def test_single_member_is_both_ends(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_one"))
        g = group["g_one"]
        self.assertIs(g.first, a)
        self.assertIs(g.last, a)
        self.assertIs(g[-1], a)

    def test_retag_moves_last(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_el"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_el"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_el"))
        b.untag("g_el")
        b.tag("g_el")
        g = group["g_el"]
        self.assertIs(g.first, a)
        self.assertIs(g.last, b)
        self.assertIs(g[-1], b)
        self.assertEqual(list(g), [a, c, b])

    def test_destroy_closes_ends(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_ed"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_ed"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_ed"))
        a.destroy()
        g = group["g_ed"]
        self.assertIs(g.first, b)
        self.assertIs(g.last, c)
        c.destroy()
        self.assertIs(g.first, b)
        self.assertIs(g.last, b)

    def test_empty_raises(self):
        g = group["g_empty_ends"]
        with self.assertRaises(IndexError) as ctx:
            g.first
        self.assertIn("group['g_empty_ends'] is empty", str(ctx.exception))
        with self.assertRaises(IndexError) as ctx:
            g.last
        self.assertIn("group['g_empty_ends'] is empty", str(ctx.exception))
        with self.assertRaises(IndexError) as ctx:
            g[0]
        self.assertIn("group['g_empty_ends'] is empty", str(ctx.exception))
        with self.assertRaises(IndexError) as ctx:
            g[-1]
        self.assertIn("group['g_empty_ends'] is empty", str(ctx.exception))
        snap = group["g_empty_ends"] | group["g_empty_ends_b"]
        with self.assertRaises(IndexError) as ctx:
            snap.first
        self.assertIn("this group is empty", str(ctx.exception))

    def test_out_of_range_names_the_group(self):
        self.track(Circle(center=(0, 0), radius=1, group="g_oor"))
        with self.assertRaises(IndexError) as ctx:
            group["g_oor"][5]
        msg = str(ctx.exception)
        self.assertIn("group['g_oor']", msg)
        self.assertIn("1 member", msg)

    def test_root_raises(self):
        with self.assertRaises(TypeError) as ctx:
            group.first
        self.assertIn("root group", str(ctx.exception))
        self.assertIn("group['wasp'].first", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            group.last
        self.assertIn("group['wasp'].last", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            group[0]
        self.assertIn("group['wasp'][0]", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            group[-1]
        self.assertIn("root group", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            group[0:1]
        self.assertIn("root group", str(ctx.exception))

    def test_slice_returns_member_list(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_sl"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_sl"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_sl"))
        g = group["g_sl"]
        mid = g[1:3]
        self.assertEqual(mid, [b, c])
        self.assertIsInstance(mid, list)
        self.assertEqual(g[:1], [a])
        self.assertEqual(g[-2:], [b, c])
        self.assertEqual(g[::2], [a, c])
        self.assertEqual(g[5:9], [])
        self.assertEqual(group["g_empty_sl"][0:2], [])

    def test_slice_is_a_copy(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_slc"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_slc"))
        c = self.track(Circle(center=(2, 0), radius=1, group="g_slc"))
        snapped = group["g_slc"][1:]
        c.destroy()
        extra = self.track(Circle(center=(3, 0), radius=1, group="g_slc"))
        self.assertEqual(snapped, [b, c])
        self.assertEqual(list(group["g_slc"]), [a, b, extra])

    def test_snapshot_and_formula(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="g_ef_a"))
        b = self.track(Circle(center=(1, 0), radius=1, group="g_ef_b"))
        snap = group["g_ef_a"] | group["g_ef_b"]
        self.assertIs(snap.first, a)
        self.assertIs(snap.last, b)
        self.assertIs(snap[-1], b)
        self.assertEqual(snap[:1], [a])
        group["g_ef_en"] @= lambda: group["g_ef_a"] | group["g_ef_b"]
        self.assertIs(group["g_ef_en"].first, a)
        self.assertIs(group["g_ef_en"].last, b)
        extra = self.track(Circle(center=(2, 0), radius=1, group="g_ef_a"))
        self.assertIs(group["g_ef_en"].first, a)
        self.assertIs(group["g_ef_en"].last, b)
        self.assertEqual(list(group["g_ef_en"]), [a, extra, b])
        extra.untag("g_ef_a")
        extra.tag("g_ef_b")
        self.assertIs(group["g_ef_en"].last, extra)


class TestGroupFormula(RegistryTestCase):
    def test_live_union_tracks_joiners_leavers_destroys(self):
        w = self.track(Circle(center=(0, 0), radius=1, group="wasp"))
        b = self.track(Circle(center=(1, 0), radius=1, group="boss"))
        group["lu_enemies"] @= lambda: group["wasp"] | group["boss"]
        g = group["lu_enemies"]
        self.assertTrue(g.is_live)
        self.assertTrue(g.is_linked)
        self.assertEqual(list(g), [w, b])
        extra = self.track(Circle(center=(2, 0), radius=1, group="wasp"))
        self.assertEqual(list(g), [w, extra, b])
        extra.untag("wasp")
        self.assertEqual(list(g), [w, b])
        b.destroy()
        self.assertEqual(list(g), [w])
        self.assertEqual(g.count, 1)

    def test_bare_live_and_str_alias(self):
        w = self.track(Circle(center=(0, 0), radius=1, group="wasp"))
        group["via_live"] @= group["wasp"]
        group["via_str"] @= "wasp"
        self.assertEqual(list(group["via_live"]), [w])
        self.assertEqual(list(group["via_str"]), [w])
        extra = self.track(Circle(center=(1, 0), radius=1, group="wasp"))
        self.assertEqual(list(group["via_live"]), [w, extra])
        self.assertEqual(list(group["via_str"]), [w, extra])

    def test_rejects_bare_snapshot_rhs(self):
        self.track(Circle(center=(0, 0), radius=1, group="ga"))
        self.track(Circle(center=(1, 0), radius=1, group="gb"))
        with self.assertRaises(TypeError) as ctx:
            group["rej_snap"] @= group["ga"] | group["gb"]
        self.assertIn("lambda", str(ctx.exception))

    def test_filter_formula_follows_predicate_changes(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="flt_src"))
        b = self.track(Circle(center=(1, 0), radius=1, group="flt_src"))
        a.hp = 0
        b.hp = 2
        group["flt_hurt"] @= lambda: group["flt_src"].filter(lambda c: float(c.hp) <= 0)
        self.assertEqual(list(group["flt_hurt"]), [a])
        b.hp = 0
        self.assertEqual(list(group["flt_hurt"]), [a, b])

    def test_held_operator_stays_live(self):
        self.track(Circle(center=(0, 0), radius=1, group="wasp"))
        group["held_enemies"] @= lambda: group["wasp"] | group["boss"]
        g = group["held_enemies"]
        later = self.track(Circle(center=(1, 0), radius=1, group="wasp"))
        self.assertIn(later, g)
        self.assertEqual(g.count, 2)

    def test_namespace_collision_and_redefinition_warns(self):
        self.track(Circle(center=(0, 0), radius=1, group="taken"))
        with self.assertRaises(TypeError):
            group["taken"] @= lambda: group["wasp"]
        group["slot"] @= lambda: group["wasp"]
        with self.assertRaises(TypeError):
            self.track(Circle(center=(1, 0), radius=1, group="slot"))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            group["slot"] @= lambda: group["boss"]
        self.assertTrue(any(issubclass(w.category, RuntimeWarning) for w in caught))

    def test_unlink_returns_empty_tag_view(self):
        self.track(Circle(center=(0, 0), radius=1, group="wasp"))
        group["ul_enemies"] @= lambda: group["wasp"]
        self.assertTrue(group["ul_enemies"].is_linked)
        group["ul_enemies"].unlink()
        self.assertFalse(group["ul_enemies"].is_linked)
        self.assertTrue(group["ul_enemies"].empty)
        self.assertTrue(group["ul_enemies"].is_live)
        later = self.track(Circle(center=(1, 0), radius=1, group="ul_enemies"))
        self.assertEqual(list(group["ul_enemies"]), [later])

    def test_cycle_mutual_and_three_deep(self):
        group["cyc_a"] @= lambda: group["cyc_b"]
        group["cyc_b"] @= lambda: group["cyc_a"]
        with self.assertRaises(RuntimeError) as ctx:
            list(group["cyc_a"])
        self.assertIn("cycle", str(ctx.exception))
        self.assertIn("cyc_a", str(ctx.exception))
        group["cyc_a"].unlink()
        group["cyc_b"].unlink()
        group["cyc_p"] @= lambda: group["cyc_q"]
        group["cyc_q"] @= lambda: group["cyc_r"]
        group["cyc_r"] @= lambda: group["cyc_p"]
        with self.assertRaises(RuntimeError) as ctx2:
            list(group["cyc_p"])
        self.assertIn("cyc_p → cyc_q → cyc_r → cyc_p", str(ctx2.exception))

    def test_nested_formulas(self):
        a = self.track(Circle(center=(0, 0), radius=1, group="na"))
        b = self.track(Circle(center=(1, 0), radius=1, group="nb"))
        c = self.track(Circle(center=(2, 0), radius=1, group="nc"))
        group["ab"] @= lambda: group["na"] | group["nb"]
        group["abc"] @= lambda: group["ab"] | group["nc"]
        self.assertEqual(list(group["abc"]), [a, b, c])

    def test_snapshot_imatmul_raises(self):
        self.track(Circle(center=(0, 0), radius=1, group="sa"))
        snap = group["sa"] | group["sb"]
        with self.assertRaises(TypeError):
            snap @= lambda: group["sa"]

    def test_call_still_raises_after_formulas(self):
        group["call_enemies"] @= lambda: group["wasp"]
        with self.assertRaises(TypeError) as ctx:
            group("call_enemies")
        self.assertIn("brackets", str(ctx.exception))

    def test_formula_union_order_stable_across_reads(self):
        a1 = self.track(Circle(center=(0, 0), radius=1, group="fa"))
        a2 = self.track(Circle(center=(1, 0), radius=1, group="fa"))
        b1 = self.track(Circle(center=(2, 0), radius=1, group="fb"))
        group["combo"] @= lambda: group["fa"] | group["fb"]
        first = list(group["combo"])
        second = list(group["combo"])
        self.assertEqual(first, [a1, a2, b1])
        self.assertEqual(second, first)


class TestNoIds(RegistryTestCase):
    """Scena has no author ids: the variable is the handle, ``group[...]`` the lookup."""

    def test_obj_global_is_gone(self):
        import scena
        self.assertFalse(hasattr(scena, "obj"))
        self.assertNotIn("obj", scena.FRAMEWORK_EXPORTS)

    def test_no_id_attribute(self):
        c = self.track(Circle(center=(0, 0), radius=1))
        self.assertFalse(hasattr(c, "id"))
        c.id = 7  # plain ink, like any author field
        self.assertEqual(c.id, 7)

    def test_id_keyword_raises_with_group_hint(self):
        for make in (lambda: Circle(**{"id": "p"}), lambda: Rect(**{"id": "p"}),
                     lambda: Point(1, 2, **{"id": "p"}), lambda: Text("hi", **{"id": "p"})):
            with self.subTest(make=make):
                with self.assertRaises(TypeError) as ctx:
                    make()
                msg = str(ctx.exception)
                self.assertIn("no ids", msg)
                self.assertIn('group["player"]', msg)

    def test_roster_tracks_live_items_in_order(self):
        a = self.track(Circle(center=(0, 0), radius=1))
        b = self.track(Circle(center=(1, 0), radius=1))
        live = _registry().live_objects()
        self.assertLess(live.index(a), live.index(b))
        self.assertTrue(_registry().is_live(a))
        a.destroy()
        self._owned.remove(a)
        self.assertFalse(_registry().is_live(a))
        self.assertNotIn(a, _registry().live_objects())

    def test_roster_keys_never_reused(self):
        # H3 class: a stale second destroy() must not drop a newer actor.
        a = Circle(center=(0, 0), radius=1)
        a.destroy()
        b = self.track(Circle(center=(0, 0), radius=1))
        a.destroy()
        self.assertTrue(_registry().is_live(b))
        self.assertNotEqual(a._reg_key, b._reg_key)


class TestResetLayers(RegistryTestCase):
    def test_reset_layers_recreates_builtins(self):
        canvas.layers.create('xtra', z=7)
        c = Circle(center=(0, 0), radius=1, layer='xtra')
        _registry().reset_layers()
        self.assertNotIn('xtra', canvas.layers)
        for name in ('top', 'default'):
            self.assertIn(name, canvas.layers)
        self.assertNotIn('no_draw', canvas.layers)
        self.assertFalse(_registry().is_live(c))


class TestCanvasRectUndrawn(RegistryTestCase):
    def test_canvas_rect_not_on_draw_list(self):
        rect = ScenaCanvas.get_current().canvas_rect
        self.assertIsNone(rect.layer)
        for layer in _registry().layers.values():
            self.assertNotIn(rect, layer._objects)


class TestParallaxLayerCreate(RegistryTestCase):
    def test_create_stores_response(self):
        canvas.layers.create(
            "bg",
            pan_response=0.3,
            zoom_response=0.2,
            rotation_response=0.5,
            scroll=(10.0, -4.0),
        )
        layer = _registry().layers["bg"]
        self.assertAlmostEqual(layer._response.pan_response, 0.3)
        self.assertAlmostEqual(layer._response.zoom_response, 0.2)
        self.assertAlmostEqual(layer._response.rotation_response, 0.5)
        self.assertEqual(layer._response.scroll, (10.0, -4.0))
        self.assertFalse(layer._is_neutral_response)
        self.assertTrue(_registry().layers.has_parallax_layers)

    def test_create_defaults_neutral(self):
        canvas.layers.create("plain")
        layer = _registry().layers["plain"]
        self.assertTrue(layer._is_neutral_response)
        self.assertFalse(_registry().layers.has_parallax_layers)

    def test_create_rejects_non_finite_response(self):
        # Regression: pan_response / zoom_response / rotation_response had
        # no finiteness check — NaN / inf silently reached the draw matrix.
        for kwargs in (
            {"pan_response": float("nan")},
            {"zoom_response": float("inf")},
            {"rotation_response": float("-inf")},
        ):
            with self.assertRaises(ValueError):
                canvas.layers.create("bad_response", **kwargs)

    def test_neutrality_epsilon(self):
        from scena.camera_response import CameraResponse
        self.assertTrue(CameraResponse(pan_response=1.0).is_neutral)
        self.assertTrue(CameraResponse(pan_response=1.0 + 1e-12).is_neutral)
        self.assertFalse(CameraResponse(pan_response=1.0 + 1e-3).is_neutral)

    def test_no_live_setter(self):
        canvas.layers.create("bg", pan_response=0.4)
        self.assertFalse(hasattr(canvas.layers, "set_pan_response"))
        layer = _registry().layers["bg"]
        import dataclasses
        with self.assertRaises(dataclasses.FrozenInstanceError):
            layer._response.pan_response = 1.0  # type: ignore[misc]

    def test_reserved_layers_always_neutral(self):
        for name in ("default", "top"):
            layer = _registry().layers[name]
            self.assertTrue(layer._is_neutral_response)
        # Cannot recreate builtins with pan_response — already exists.
        with self.assertRaises(ValueError):
            canvas.layers.create("default", pan_response=0.2)
        with self.assertRaises(ValueError):
            canvas.layers.create("top", pan_response=0.2)
        # No force= escape hatch.
        import inspect
        sig = inspect.signature(canvas.layers.create)
        self.assertNotIn("force", sig.parameters)
        self.assertNotIn("response", sig.parameters)  # author API uses knobs, not response=

    def test_has_parallax_flag_lifecycle(self):
        canvas.layers.create("a", pan_response=0.2)
        canvas.layers.create("b", z=3)  # neutral
        self.assertTrue(_registry().layers.has_parallax_layers)
        canvas.layers['b'].delete(destroy_shapes=True)
        self.assertTrue(_registry().layers.has_parallax_layers)
        canvas.layers['a'].delete(destroy_shapes=True)
        self.assertFalse(_registry().layers.has_parallax_layers)

    def test_list_info_still_works(self):
        canvas.layers.create("bg", pan_response=0.5, z=-2)
        info = {row["name"]: row for row in canvas.layers.list()}
        self.assertIn("bg", info)
        self.assertEqual(info["bg"]["z"], -2)


class TestLookupKeyTypes(RegistryTestCase):
    """A1 class (Testing Design): unhashable keys leaked ``unhashable type``."""

    def test_layer_lookup_rejects_unhashable_keys(self):
        for bad in (["default"], {"default": 1}, 3.5, True):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError) as ctx:
                    canvas.layers[bad]
                self.assertNotIn("unhashable", str(ctx.exception))
        self.assertFalse(["default"] in canvas.layers)


class TestLiveCountsIgnoreTombstones(RegistryTestCase):
    """D1 (Testing Design): ``list_info()['object_count']`` counted the ``None``
    holes a removal leaves until ``compact()``."""

    def test_list_info_counts_live_objects_only(self):
        canvas.layers.create("d1_counts", z=7)
        shapes = [self.track(Circle(layer="d1_counts")) for _ in range(3)]
        shapes[0].destroy()
        shapes[1].undraw()
        info = {d["name"]: d for d in canvas.layers.list()}
        layer = _registry().layers.get("d1_counts")
        self.assertEqual(info["d1_counts"]["object_count"], 1)
        self.assertEqual(layer._live_count, 1)
        layer._compact()
        self.assertEqual(layer._live_count, len(layer._objects))

    def test_no_engine_code_counts_a_draw_list_with_len(self):
        # Bug-class guard: ``len(<layer>._objects)`` includes removal holes.
        # Only Layer itself may use it (_live_count, _append_object's index).
        import re
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scena")
        pat = re.compile(r"len\(\s*[\w.]*\._?objects\s*\)")
        found = []
        for path in iter_files(root, ".py"):
            name = os.path.basename(path)
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if pat.search(line) and "len(self._objects)" not in line:
                        found.append(f"{name}:{n}: {line.strip()}")
        self.assertEqual(found, [], "count draw lists with Layer._live_count:\n" + "\n".join(found))


if __name__ == '__main__':
    unittest.main()
