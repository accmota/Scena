"""
``Endless``: fill the part of a layer the camera sees, slot by slot (P2).
Canvas Design, "Endless fill".

Bug classes pinned here: a seam off by one (a gap or an overlap between
slots), thrash at the build boundary, a revisited slot that builds a
different piece, a zero-width slot that loops forever, zoom-out that spawns
hundreds of pieces, and an unreferenced one-line ``Endless(...)`` that the
weak roster collects (the fill silently stops).

    python tests/run_tiers.py focused test_endless
"""

from __future__ import annotations

import gc
import math
import os
import random
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402
from system_support import SystemTestCase  # noqa: E402

from scena import (  # noqa: E402
    Act, Circle, Endless, Polygon, Rect, Sprite, canvas, change_act, group, init,
)
from scena.canvas import ScenaCanvas  # noqa: E402
from scena.endless import _SLOT_CAP, Slot, _mix  # noqa: E402
from scena.registry import BUILT_IN_LAYERS, ParallaxLayerError  # noqa: E402

MEDIA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "examples", "media")
STAR = os.path.join(MEDIA, "space", "star_gold.png")
SHIP = os.path.join(MEDIA, "space", "playerShip1_red.png")


def _registry():
    return ScenaCanvas.get_current().registry


def _floor(slot, y=0.0, h=20.0, **kw):
    return Rect(top_left=(slot.left, y + h), width=slot.right - slot.left, height=h, **kw)


class EndlessCase(SystemTestCase, unittest.TestCase):
    world_draw = False

    @classmethod
    def setUpClass(cls):
        # Slot counts (the cap tests, free roam under _SLOT_CAP) follow the
        # view area: pin the design size instead of inheriting the last
        # module's init() (boot() inits 400x300 once per process; the deep
        # serial pass ran this after an 800x600 module and hit the cap).
        boot()
        init(width=400, height=300)

    def setUp(self):
        super().setUp()
        canvas.reset_view()
        canvas.layers.create("pista", below="default")

    def tearDown(self):
        for e in [o for o in _registry().live_objects() if isinstance(o, Endless)]:
            e.destroy()
        for name in list(canvas.layers):
            if name not in BUILT_IN_LAYERS:
                try:
                    canvas.layers[name].delete(destroy_shapes=True)
                except Exception:
                    pass
        canvas.reset_view()
        super().tearDown()

    # --- helpers --------------------------------------------------------------

    def assertCovers1D(self, e, view=None):
        """The live slots form one run of indices whose union covers the view."""
        v = view or canvas.layers[e._layer_key].view
        lo, hi = (v.left, v.right) if e._axis == "x" else (v.bottom, v.top)
        keys = sorted(e._live)
        self.assertTrue(keys, "no live slots")
        self.assertEqual(keys, list(range(keys[0], keys[-1] + 1)), "hole in live slots")
        for a, b in zip(keys, keys[1:]):
            self.assertAlmostEqual(e._bounds(a)[1], e._bounds(b)[0], places=6, msg="seam")
        self.assertLessEqual(e._bounds(keys[0])[0], lo + 1e-6)
        self.assertGreaterEqual(e._bounds(keys[-1])[1], hi - 1e-6)

    def assertCoversXY(self, e):
        v = canvas.layers[e._layer_key].view
        (x0, y0), (w, h) = e._start, e._step
        for i in range(math.floor((v.left - x0) / w), math.floor((v.right - x0) / w) + 1):
            for j in range(math.floor((v.bottom - y0) / h), math.floor((v.top - y0) / h) + 1):
                self.assertIn((i, j), e._live)

    def pan_by(self, dx, dy=0.0):
        canvas.pan_to(canvas.pan_x + dx, canvas.pan_y + dy)


class TestConstructionErrors(EndlessCase):

    def test_reserved_layers_raise_with_the_create_fix(self):
        for name in ("default", "top", "ui"):
            with self.subTest(layer=name):
                with self.assertRaises(ValueError) as cm:
                    Endless(name, _floor, step=100)
                self.assertIn("canvas.layers.create('pista', below='default')", str(cm.exception))

    def test_missing_layer_names_the_create_fix(self):
        with self.assertRaisesRegex(ValueError, r"canvas.layers.create\('nada'\)"):
            Endless("nada", _floor, step=100)

    def test_builder_needs_step(self):
        with self.assertRaisesRegex(TypeError, "a builder needs step="):
            Endless("pista", _floor)

    def test_argument_combinations(self):
        cases = [
            (dict(pieces=STAR, step=100, gap=10), TypeError, "not both"),
            (dict(pieces=_floor, axis="xy", step=100), TypeError, r"step=\(w, h\)"),
            (dict(pieces=_floor, axis="xy", step=lambda s: 1), TypeError, r"step=\(w, h\)"),
            (dict(pieces=STAR, axis="xy"), TypeError, r"step=\(w, h\)"),
            (dict(pieces=STAR, axis="xy", step=(10, 10), gap=5), TypeError, "no gap"),
            (dict(pieces=_floor, step=(10, 10)), TypeError, "axis='xy'"),
            (dict(pieces=STAR, axis="y", bottom=10), TypeError, "left="),
            (dict(pieces=STAR, axis="x", left=10), TypeError, "bottom="),
            (dict(pieces=STAR, axis="xy", step=(9, 9), bottom=1), TypeError, "centers"),
            (dict(pieces=_floor, step=10, bottom=5), TypeError, "builder places"),
            (dict(pieces=_floor, step=10, group="chao"), TypeError, "their own group"),
            (dict(pieces=[STAR, _floor]), TypeError, "slot.rng.choice"),
            (dict(pieces=[]), ValueError, "empty"),
            (dict(pieces=42), TypeError, "builder fn"),
            (dict(pieces=_floor, step=100, axis="z"), ValueError, "axis"),
            (dict(pieces=_floor, step=0), ValueError, "> 0"),
            (dict(pieces=_floor, step=-5), ValueError, "> 0"),
            (dict(pieces=_floor, step=100, seed="abc"), TypeError, "seed"),
            (dict(pieces=_floor, step=100, seed=True), TypeError, "seed"),
            (dict(pieces=STAR, gap=(50, 10)), ValueError, "lo <= hi"),
            (dict(pieces=_floor, step=10, height=40), TypeError, "sizes its own"),
            (dict(pieces=_floor, step=10, width=40), TypeError, "sizes its own"),
        ]
        for kw, exc, pattern in cases:
            with self.subTest(kw=kw):
                pieces = kw.pop("pieces")
                with self.assertRaisesRegex(exc, pattern):
                    Endless("pista", pieces, **kw)

    def test_failed_construction_leaves_nothing(self):
        before = len(canvas.layers["pista"]._objects)
        calls = []

        def bad(slot):
            calls.append(slot.i)
            if len(calls) > 2:
                return None
            return _floor(slot)

        with self.assertRaisesRegex(TypeError, r"returned None"):
            Endless("pista", bad, step=50)
        live = [o for o in canvas.layers["pista"]._objects if o is not None and o.is_alive]
        self.assertEqual(len(live), before)
        self.assertFalse(any(isinstance(o, Endless) for o in _registry()._held))
        self.assertFalse(any(isinstance(o, Endless) for o in _registry().live_objects()))


class TestFill1D(EndlessCase):

    def test_first_frame_is_full(self):
        e = Endless("pista", _floor, step=97)
        self.assertCovers1D(e)

    def test_camera_moves_long_run_stays_full_and_bounded(self):
        builds = []

        def trecho(slot):
            builds.append(slot.i)
            return _floor(slot)

        e = Endless("pista", trecho, step=lambda s: s.rng.choice([60, 90, 150]))
        width = canvas.game_view.width
        for k in range(600):
            self.pan_by(7.0)
            self.w.step(1)
            self.assertCovers1D(e)
            # Never more than the keep window (view ± 1 extent) worth of slots.
            self.assertLessEqual(len(e._live), int(3 * width / 60) + 3)
        # Each slot built once on a one-way trip.
        self.assertEqual(len(builds), len(set(builds)))

    def test_backward_travel_fills_negative_slots(self):
        e = Endless("pista", _floor, step=lambda s: s.rng.uniform(40, 120), seed=7)
        for _ in range(200):
            self.pan_by(-13.0)
            self.w.step(1)
            self.assertCovers1D(e)
        self.assertLess(min(e._live), -10)

    def test_no_thrash_at_the_boundary(self):
        builds = []
        e = Endless("pista", lambda s: builds.append(s.i) or _floor(s), step=100)
        start = len(builds)
        width = canvas.game_view.width
        # Jitter by less than the dead band (behind - ahead = half a view).
        for k in range(300):
            self.pan_by(0.2 * width if k % 2 == 0 else -0.2 * width)
            self.w.step(1)
        self.assertLessEqual(len(builds) - start, 2)

    def test_revisit_rebuilds_the_same_piece(self):
        draws = {}

        def trecho(slot):
            value = (slot.rng.random(), slot.left)
            draws.setdefault(slot.i, []).append(value)
            return _floor(slot)

        Endless("pista", trecho, step=lambda s: s.rng.choice([70, 130]))
        canvas.pan_to(20000, canvas.pan_y)
        self.w.step(1)
        canvas.pan_to(0, canvas.pan_y)
        self.w.step(1)
        revisited = [i for i, v in draws.items() if len(v) > 1]
        self.assertTrue(revisited)
        for i in revisited:
            self.assertEqual(len(set(draws[i])), 1, f"slot {i} changed on revisit")

    def test_same_seed_same_world_other_seed_other_world(self):
        def record(store):
            def b(slot):
                store.append((slot.i, slot.left, slot.rng.random()))
                return []
            return b

        a, b, c = [], [], []
        Endless("pista", record(a), step=lambda s: s.rng.uniform(30, 90), seed=11)
        Endless("pista", record(b), step=lambda s: s.rng.uniform(30, 90), seed=11)
        Endless("pista", record(c), step=lambda s: s.rng.uniform(30, 90), seed=12)
        self.assertEqual(sorted(a), sorted(b))
        self.assertNotEqual(sorted(a), sorted(c))

    def test_seed_none_draws_a_run_seed_and_reports_it(self):
        random.seed(5)
        e = Endless("pista", lambda s: [], step=50)
        self.assertIsInstance(e.seed, int)
        f = Endless("pista", lambda s: [], step=50, seed=e.seed)
        self.assertEqual(f.seed, e.seed)
        with self.assertRaises(AttributeError):
            e.seed = 3

    def test_seed_mixing_is_stable(self):
        # Pinned values: the same int stream on every Python version.
        self.assertEqual(_mix(42, 3), 0x725FFCDD5E24A498)
        self.assertEqual(_mix(0, 0), 0x96DCB1D7126A6EBA)
        self.assertEqual(_mix(7, -1), 0xC8B6FF9CECE42ABF)
        self.assertNotEqual(_mix(1, 2), _mix(2, 1))
        self.assertNotEqual(_mix(7, -1), _mix(7, 1))
        # ``random.Random(int)`` is stable across versions for int seeds.
        self.assertEqual(random.Random(_mix(42, 3)).random(), 0.40051603999944574)

    def test_slot_edges_are_absolute_and_pieces_never_move(self):
        made = {}

        def trecho(slot):
            r = _floor(slot)
            made[slot.i] = (r, (slot.left, slot.right), (r.center.x, r.center.y))
            return r

        Endless("pista", trecho, step=120, start=35)
        for i, (r, (left, right), _c) in made.items():
            self.assertAlmostEqual(left, 35 + 120 * i)
            self.assertAlmostEqual(right - left, 120)
        for _ in range(40):
            self.pan_by(25)
            self.w.step(1)
        for i, (r, _edges, c) in made.items():
            if r.is_alive:
                self.assertEqual((r.center.x, r.center.y), c)

    def test_start_defaults_to_the_view_near_edge(self):
        canvas.pan_to(1000, canvas.pan_y)
        e = Endless("pista", lambda s: [], step=100)
        self.assertAlmostEqual(e._start, canvas.game_view.left)
        self.assertAlmostEqual(e._bounds(0)[0], canvas.game_view.left)

    def test_step_function_long_jump_builds_no_intermediate_slots(self):
        builds = []
        e = Endless("pista", lambda s: builds.append(s.i) or [],
                    step=lambda s: s.rng.choice([100, 200]), seed=1)
        before = len(builds)
        canvas.pan_to(200000, canvas.pan_y)
        self.w.step(1)
        self.assertCovers1D(e)
        self.assertLess(len(builds) - before, 20)

    def test_step_function_is_pure_called_twice_same_width(self):
        calls = []

        def step(slot):
            calls.append(slot.i)
            return slot.rng.choice([50, 75, 125])

        e = Endless("pista", lambda s: [], step=step, seed=9)
        f = Endless("pista", lambda s: [], step=step, seed=9)
        for i in range(-5, 15):
            self.assertEqual(e._bounds(i), f._bounds(i))
        self.assertGreater(calls.count(0), 1)

    def test_step_function_bad_width_names_the_slot(self):
        for bad, exc in ((0, ValueError), (-3, ValueError), (math.nan, ValueError),
                         (math.inf, ValueError), ("wide", TypeError)):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(exc, "slot i="):
                    Endless("pista", lambda s: [], step=lambda s, b=bad: b)

    def test_empty_slots(self):
        e = Endless("pista", lambda s: [] if s.i % 2 else _floor(s), step=60)
        self.assertCovers1D(e)
        self.assertTrue(any(not e._live[k] for k in e._live))
        self.assertEqual(len(e.pieces), sum(1 for k in e._live if k % 2 == 0))

    def test_builder_return_errors_name_the_slot(self):
        for ret, pattern in ((None, "returned None"), (42, "returned int"),
                             ([Circle(center=(0, 0), radius=1), "x"], "holding str")):
            with self.subTest(ret=ret):
                with self.assertRaisesRegex(TypeError, r"slot i=-?\d+"):
                    Endless("pista", lambda s, r=ret: r, step=100)

    def test_pieces_in_axis_order(self):
        e = Endless("pista", _floor, step=50)
        xs = [p.center.x for p in e.pieces]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(len(xs), len(e._live))

    def test_slot_chance_shares_the_slot_stream(self):
        seen = {}

        def b(slot):
            seen[slot.i] = (slot.chance(0.5), slot.rng.random())
            return []

        e = Endless("pista", b, step=100, seed=21)
        for i, (hit, nxt) in seen.items():
            r = random.Random(_mix(e.seed, i))
            self.assertEqual(hit, r.random() < 0.5)
            self.assertEqual(nxt, r.random())

    def test_slot_chance_validates_like_chance(self):
        errors = []

        def b(slot):
            try:
                slot.chance(30)
            except ValueError as exc:
                errors.append(str(exc))
            return []

        Endless("pista", b, step=500)
        self.assertIn("slot.chance(0.30)", errors[0])

    def test_slot_fields_by_axis(self):
        got = {}

        def b(slot):
            got["slot"] = slot
            return []

        Endless("pista", b, step=100)
        s = got["slot"]
        self.assertIsInstance(s, Slot)
        for name in ("bottom", "top", "box", "j"):
            with self.subTest(field=name):
                with self.assertRaises(AttributeError):
                    getattr(s, name)
        Endless("pista", b, axis="y", step=100)
        s = got["slot"]
        for name in ("left", "right", "box"):
            with self.assertRaises(AttributeError):
                getattr(s, name)
        self.assertLess(s.bottom, s.top)

    def test_terrain_borders_match_across_slots(self):
        def altura(x):
            return 100 + 40 * math.sin(x * 0.01) + 15 * math.sin(x * 0.037)

        ends = {}

        def terreno(slot):
            pecas, passo = [], 25
            x = slot.left
            while x < slot.right - 1e-9:
                x2 = min(x + passo, slot.right)
                pecas.append(Polygon(points=[(x, 0), (x2, 0), (x2, altura(x2)), (x, altura(x))]))
                x = x2
            ends[slot.i] = (altura(slot.left), altura(slot.right))
            return pecas

        Endless("pista", terreno, step=lambda s: s.rng.choice([100, 160, 230]))
        for i in ends:
            if i + 1 in ends:
                self.assertAlmostEqual(ends[i][1], ends[i + 1][0], places=9)


class TestIndexAt(EndlessCase):

    def test_fixed(self):
        e = Endless("pista", lambda s: [], step=100, start=0)
        self.assertEqual(e.index_at(0), 0)
        self.assertEqual(e.index_at(99.9), 0)
        self.assertEqual(e.index_at(100), 1)
        self.assertEqual(e.index_at(-0.1), -1)
        self.assertEqual(e.index_at(12345), 123)

    def test_step_function_and_measured(self):
        e = Endless("pista", lambda s: [], step=lambda s: s.rng.choice([30, 70]), start=0, seed=4)
        f = Endless("pista", [STAR, SHIP], gap=(5, 25), start=0, seed=4)
        for en in (e, f):
            for x in (-500.0, -1.0, 0.0, 1.0, 333.3, 5000.0):
                i = en.index_at(x)
                near, far = en._bounds(i)
                self.assertLessEqual(near, x)
                self.assertLess(x, far)

    def test_xy_and_type_errors(self):
        e = Endless("pista", lambda s: [], axis="xy", step=(100, 50), start=(0, 0))
        self.assertEqual(e.index_at((250, -10)), (2, -1))
        with self.assertRaises(TypeError):
            e.index_at(5)
        f = Endless("pista", lambda s: [], step=100)
        with self.assertRaisesRegex(TypeError, "one coordinate"):
            f.index_at((1, 2))


class TestImages(EndlessCase):

    def test_measured_extent_equals_the_built_sprite_and_gaps_hold(self):
        e = Endless("pista", [STAR, SHIP], gap=(10, 40), bottom=50, seed=3)
        keys = sorted(e._live)
        for k in keys:
            (sprite,) = e._live[k]
            near, far = e._bounds(k)
            self.assertAlmostEqual(sprite.center.x - sprite.width / 2, near, places=6)
            self.assertAlmostEqual(sprite.center.y - sprite.height / 2, 50, places=6)
            gap = far - near - sprite.width
            self.assertGreaterEqual(gap, 10 - 1e-9)
            self.assertLessEqual(gap, 40 + 1e-9)
        probe = Sprite(SHIP)
        self.assertAlmostEqual(e._measure_image(SHIP), probe.width)
        probe.destroy()

    def test_image_pick_is_stable_on_revisit(self):
        e = Endless("pista", [STAR, SHIP], seed=8)
        first = {k: (e._live[k][0].width, e._live[k][0].height) for k in e._live}
        self.assertEqual(len(set(first.values())), 2)       # both images in use
        x0 = canvas.pan_x
        canvas.pan_to(50000, canvas.pan_y)
        self.w.step(1)
        self.assertFalse(set(first) & set(e._live))
        canvas.pan_to(x0, canvas.pan_y)
        self.w.step(1)
        for k, size in first.items():
            self.assertEqual((e._live[k][0].width, e._live[k][0].height), size)
        # Same extents → same edges as a fresh twin with the same seed.
        twin = Endless("pista", [STAR, SHIP], seed=8, start=e._start)
        for i in range(-3, 10):
            self.assertEqual(e._bounds(i), twin._bounds(i))

    def test_non_positive_extent_raises_naming_step(self):
        with self.assertRaisesRegex(ValueError, "Pass step="):
            Endless("pista", STAR, gap=-10000)

    def test_height_sizes_every_piece_and_the_slot_follows(self):
        # A band of background art wants the size of the screen; a bare
        # Sprite(path) is 48 units on its longer side (tutorial 16, 2026-10-09:
        # one line of Endless gave a row of 48-unit thumbnails).
        e = Endless("pista", [STAR, SHIP], height=120, bottom=0, seed=4)
        keys = sorted(e._live)
        self.assertTrue(keys)
        for k in keys:
            (sprite,) = e._live[k]
            near, far = e._bounds(k)
            self.assertAlmostEqual(sprite.height, 120, places=6)
            self.assertAlmostEqual(far - near, sprite.width, places=6)       # no gap, no overlap
            self.assertAlmostEqual(sprite.center.y - 60, 0, places=6)
        self.assertCovers1D(e)
        for kw, side in ((dict(width=90), "width"), (dict(size=90), None)):
            with self.subTest(kw=kw):
                f = Endless("pista", SHIP, seed=1, **kw)
                probe = Sprite(SHIP, **kw)
                for p in f.pieces:
                    self.assertAlmostEqual(p.width, probe.width, places=6)
                    self.assertAlmostEqual(p.height, probe.height, places=6)
                probe.destroy()
                f.destroy()

    def test_group_and_layer(self):
        canvas.layers.create("ceu", pan_response=0.3)
        e = Endless("ceu", STAR, gap=5, group="nuvem")
        self.assertTrue(e.pieces)
        for p in e.pieces:
            self.assertEqual(p.layer, "ceu")
            self.assertTrue(p.tagged("nuvem"))


class TestOwnership(EndlessCase):

    def test_returned_pieces_owned_created_ones_belong_to_the_author(self):
        extras = []

        def b(slot):
            extras.append(Circle(center=(slot.left, 200), radius=3))
            return _floor(slot)

        e = Endless("pista", b, step=100)
        owned = list(e.pieces)
        canvas.pan_to(100000, canvas.pan_y)
        self.w.step(1)
        self.assertTrue(all(not p.is_alive for p in owned))
        self.assertTrue(all(c.is_alive for c in extras))
        for c in extras:
            c.destroy()

    def test_destroyed_piece_is_consumed_until_the_slot_comes_back(self):
        builds = []
        e = Endless("pista", lambda s: builds.append(s.i) or _floor(s), step=100)
        k = sorted(e._live)[len(e._live) // 2]
        e._live[k][0].destroy()
        n = len(builds)
        for _ in range(10):
            self.w.step(1)
        self.assertEqual(len(builds), n)          # not rebuilt while in view
        self.assertNotIn(k, [p for p in builds[n:]])
        canvas.pan_to(100000, canvas.pan_y)
        self.w.step(1)
        canvas.pan_to(0, canvas.pan_y)
        self.w.step(1)
        self.assertTrue(e._live[k] and e._live[k][0].is_alive)   # back after leaving

    def test_layer_clear_counts_as_consumed(self):
        e = Endless("pista", _floor, step=100)
        canvas.layers["pista"].clear(hard=True)
        self.w.step(3)
        self.assertEqual(e.pieces, [])

    def test_other_objects_on_the_layer_are_untouched(self):
        mine = Circle(center=(-99999, 0), radius=4, layer="pista")
        Endless("pista", _floor, step=100)
        canvas.pan_to(100000, canvas.pan_y)
        self.w.step(2)
        self.assertTrue(mine.is_alive)
        self.assertEqual((mine.center.x, mine.center.y), (-99999.0, 0.0))
        mine.destroy()

    def test_pieces_are_born_on_the_layer_or_moved_there(self):
        canvas.layers.create("outra")

        def b(slot):
            return [_floor(slot), Circle(center=(slot.left, 5), radius=2, layer="outra")]

        e = Endless("pista", b, step=100)
        self.assertTrue(e.pieces)
        self.assertTrue(all(p.layer == "pista" for p in e.pieces))
        self.assertEqual(canvas.layers.default, "default")

    def test_collidable_piece_on_a_parallax_layer_raises(self):
        canvas.layers.create("ceu", pan_response=0.4)

        def b(slot):
            r = _floor(slot)
            r.collidable = True
            return r

        with self.assertRaises(ParallaxLayerError):
            Endless("ceu", b, step=100)

    def test_several_endless_on_one_layer_are_independent(self):
        a = Endless("pista", _floor, step=100)
        b = Endless("pista", lambda s: Circle(center=(s.left, 90), radius=4), step=70)
        a.destroy()
        self.assertEqual(a.pieces, [])
        self.assertTrue(b.pieces and all(p.is_alive for p in b.pieces))


class TestLifecycle(EndlessCase):

    def test_one_line_endless_survives_gc(self):
        Endless("pista", _floor, step=100)
        gc.collect()
        for _ in range(30):
            self.pan_by(40)
            self.w.step(1)
            gc.collect()
        e = next(o for o in _registry().live_objects() if isinstance(o, Endless))
        self.assertCovers1D(e)

    def test_destroy_destroys_pieces_and_stops(self):
        e = Endless("pista", _floor, step=100)
        pieces = e.pieces
        e.destroy()
        self.assertTrue(all(not p.is_alive for p in pieces))
        self.assertNotIn(e, _registry()._held)
        canvas.pan_to(5000, canvas.pan_y)
        self.w.step(2)
        self.assertEqual(e.pieces, [])
        e.destroy()                                 # second call: no-op

    def test_active_false_freezes_the_fill(self):
        e = Endless("pista", _floor, step=100)
        keys = sorted(e._live)
        e.active = False
        canvas.pan_to(5000, canvas.pan_y)
        self.w.step(3)
        self.assertEqual(sorted(e._live), keys)
        e.active = True
        self.w.step(1)
        self.assertCovers1D(e)

    def test_act_teardown(self):
        made = {}

        class Corrida(Act):
            def setup(self):
                canvas.layers.create("trilha", below="default")
                made["e"] = Endless("trilha", _floor, step=100)
                made["pieces"] = list(made["e"].pieces)

        class Fim(Act):
            def setup(self):
                pass

        self.w.begin_game(Corrida)
        self.w.step(2)
        e = made["e"]
        self.assertTrue(e.is_alive)
        change_act(Fim)
        self.w.step(1)
        self.assertFalse(e.is_alive)
        self.assertTrue(all(not p.is_alive for p in made["pieces"]))
        self.assertNotIn(e, _registry()._held)


class TestCapAndWarnings(EndlessCase):

    def test_cap_1d_warns_once(self):
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            e = Endless("pista", lambda s: [], step=0.5)
            self.w.step(3)
        self.assertEqual(len(e._live), _SLOT_CAP)
        msgs = [str(w.message) for w in rec if "Endless" in str(w.message)]
        self.assertEqual(len(msgs), 1)
        self.assertIn("step=", msgs[0])
        # Capped fill keeps the slots around the view center.
        mid = e.index_at(canvas.game_view.center.x)
        self.assertIn(mid, e._live)

    def test_cap_xy_counts_cells(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            e = Endless("pista", lambda s: [], axis="xy", step=(5, 5))
        self.assertEqual(len(e._live), _SLOT_CAP)

    def test_drift_warning_fires_once_for_treadmill_misuse(self):
        e = Endless("pista", _floor, step=100)
        width = canvas.game_view.width

        def update(dt):
            group_pieces = e.pieces
            for p in group_pieces:
                p.move_by(-width * 0.2, 0)

        self.w.on_update(update)
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            self.w.step(30)
        msgs = [str(w.message) for w in rec if "moved away from their slots" in str(w.message)]
        self.assertEqual(len(msgs), 1)

    def test_drift_warning_silent_when_the_camera_moves(self):
        Endless("pista", _floor, step=100)
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            for _ in range(200):
                self.pan_by(15)
                self.w.step(1)
        self.assertFalse([w for w in rec if "Endless" in str(w.message)])


class TestOtherLayers(EndlessCase):

    def test_parallax_layer_fills_its_own_view(self):
        canvas.layers.create("montes", pan_response=0.3)
        e = Endless("montes", lambda s: Circle(center=(s.left, 100), radius=10), step=80)
        for _ in range(300):
            self.pan_by(37)
            self.w.step(1)
            self.assertCovers1D(e)
        # It moved only 30% as far as the camera.
        self.assertLess(canvas.layers["montes"].view.left, 0.31 * canvas.pan_x + 1)

    def test_fixed_camera_scroll_layer_axis_y(self):
        canvas.layers.create("nuvens", scroll=(0, -180))
        e = Endless("nuvens", lambda s: Circle(center=(50, s.bottom), radius=6), axis="y", step=60)
        for _ in range(400):
            self.w.step(1)
            self.assertCovers1D(e)
        self.assertGreater(canvas.layers["nuvens"].view.bottom, 1000)

    def test_scroll_stop_with_p3(self):
        nuvens = canvas.layers.create("nuvens", scroll=(0, -180))
        e = Endless("nuvens", lambda s: [], axis="y", step=60)
        self.w.step(10)
        nuvens.scroll = (0, 0)
        keys = sorted(e._live)
        self.w.step(10)
        self.assertEqual(sorted(e._live), keys)

    def test_xy_grid_free_roam(self):
        e = Endless("pista", lambda s: Circle(center=s.box.center, radius=3) if s.chance(0.3) else [],
                    axis="xy", step=(120, 90), seed=2)
        self.assertCoversXY(e)
        rng = random.Random(0)
        for _ in range(200):
            self.pan_by(rng.uniform(-60, 80), rng.uniform(-60, 80))
            self.w.step(1)
            self.assertCoversXY(e)
            self.assertLess(len(e._live), _SLOT_CAP)

    def test_xy_revisit_same_cells(self):
        seen = {}

        def b(slot):
            seen.setdefault((slot.i, slot.j), set()).add(slot.rng.random())
            return []

        Endless("pista", b, axis="xy", step=(100, 100), seed=6)
        canvas.pan_to(9000, -7000)
        self.w.step(1)
        canvas.pan_to(0, 0)
        self.w.step(1)
        self.assertTrue(all(len(v) == 1 for v in seen.values()))


if __name__ == "__main__":
    unittest.main()
