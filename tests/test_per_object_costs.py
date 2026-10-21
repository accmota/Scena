"""
Per-object costs an ordinary game pays every frame, and the fast paths that
cut them (found tuning ``examples/revoada.py``: 120 rotating Triangles).

Bug classes guarded:

* **A same-value paint write that redoes the whole write**: ``shape.color =
  "red"`` every frame re-parsed the colour, derived the outline and dropped
  the cached Skia paints (~17 µs a shape, and the draw rebuilt them); ``fill =``
  / ``line =`` the same. The short-circuit must change nothing a full write
  would have changed (metamorphic check against the full path), keep a slow
  fade exact, and stay off under a look.
* **An author ``Vec2(x, y)`` built through the general constructor**
  (~3.7 µs against ~0.5 for ``Vec2.temp``) and **``ship.vel = Vec2(…)`` paying
  every coercion** (~9.5 µs against ~1.7 in place). The fast paths must leave
  the state the general path leaves.
* **A measured Box built in full on every read** (``canvas.game_view`` ~16 µs:
  ``ship.confine(canvas.game_view)`` per actor per frame). The template fast
  path must leave the general path's dict.
* **``confine(by="box" / "overlap")`` measuring a frame instead of the
  outline**: a Triangle refused ("Triangle.box is unsupported"), and a turned
  Circle stopped short of the wall. It now measures the outline of every kind
  (the full matrix: tests/test_confine.py ``TestOutlineEveryKind``).
* **CheapGlow re-reading the host's pose once per band** (4 bands, 2 reads
  each: ~28 µs a Triangle, 3× a Glow). One geometry draw, replayed; the
  pixels must not change.

Run:

    python tests/run_tiers.py focused test_per_object_costs
"""
from __future__ import annotations

import math
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skia  # noqa: E402

import scena.box as box_mod  # noqa: E402
import scena.style as style_mod  # noqa: E402
import scena.visuals as visuals_mod  # noqa: E402
from scena import (  # noqa: E402
    Box, CheapGlow, Circle, Color, Concave, Ellipse, Line, Neon, Polygon, Rect,
    RegularPolygon, Square, Triangle, Vec2, canvas, init,
)
from scena.state import ephemeral_creation  # noqa: E402


class _World(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        canvas.reset_view()
        self._owned = []

    def tearDown(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass

    def own(self, obj):
        self._owned.append(obj)
        return obj


def _paint_state(s):
    return (s.fill, s.line, s.color)


class TestSamePaintWrites(_World):
    def test_same_colour_keeps_the_cached_paints(self):
        for value in ("red", Color(0.2, 0.4, 0.6)):
            s = self.own(Triangle(radius=9, center=(100, 100)))
            s.color = value
            fill_paint = s._to_skia_fill_paint()
            line_paint = s._to_skia_line_paint()
            fill, line = s._fill, s._line
            s.color = value
            # An equal Color built anew is the same plain value too.
            s.color = value if isinstance(value, str) else Color(value)
            self.assertIs(s._fill, fill)
            self.assertIs(s._line, line)
            self.assertIs(s._to_skia_fill_paint(), fill_paint)
            self.assertIs(s._to_skia_line_paint(), line_paint)

    def test_same_fill_and_line_keep_the_cached_paints(self):
        s = self.own(Rect(width=20, height=10, center=(100, 100)))
        dark = Color(0.1, 0.1, 0.1)
        s.fill = "gold"
        s.line = dark
        fp, lp = s._to_skia_fill_paint(), s._to_skia_line_paint()
        s.fill = "gold"
        s.line = dark
        self.assertIs(s._to_skia_fill_paint(), fp)
        self.assertIs(s._to_skia_line_paint(), lp)
        # fill / line take the same object or an equal str only: an equal
        # Color built anew is written (set_color's own fresh Colors pass
        # unchecked), with the same value.
        s.line = Color(0.1, 0.1, 0.1)
        self.assertEqual(s.line, dark)

    def test_a_new_colour_still_repaints(self):
        s = self.own(Circle(radius=9, center=(100, 100)))
        s.color = "red"
        s.color = "blue"
        self.assertEqual(s.fill, Color("blue"))
        self.assertEqual(s.line, Color("blue").contrast_tone(intensity=0.2))

    def test_slow_fade_is_exact(self):
        # Color == rounds to 3 decimals: a key on == would stall a slow fade.
        s = self.own(Circle(radius=9, center=(100, 100)))
        s.color = Color(0.5, 0.0, 0.0)
        s.color = Color(0.5004, 0.0, 0.0)
        self.assertEqual(s._fill._r, 0.5004)
        s.fill = Color(0.5006, 0.0, 0.0)
        self.assertEqual(s._fill._r, 0.5006)
        s.fill = Color(0.5006, 0.0, 0.0)        # equal, not the same object: written
        self.assertEqual(s._fill._r, 0.5006)

    def test_destroyed_shape_still_refuses(self):
        from scena.entity import DestroyedError
        s = Circle(radius=9, center=(100, 100))
        s.color = "red"
        s.destroy()
        with self.assertRaises(DestroyedError):
            s.set_color("red")

    def test_short_circuit_changes_nothing_a_full_write_would(self):
        """Metamorphic: one random write sequence on two shapes, the second
        with the same-value check off; every channel agrees after each step."""
        rng = random.Random(7)
        kinds = (
            lambda: Triangle(radius=9, center=(50, 50)),
            lambda: Circle(radius=9, center=(50, 50)),
            lambda: Line(p1=(0, 0), p2=(30, 10)),
            lambda: Rect(width=20, height=10, center=(50, 50)),
        )
        colours = ("red", "blue", Color(0.3, 0.6, 0.9), Color(0.3, 0.6, 0.9, 0.5), (1, 0.5, 0))

        def ops(s, r):
            c = colours[r.randrange(len(colours))]
            return [
                lambda: setattr(s, "color", c),
                lambda: setattr(s, "fill", c),
                lambda: setattr(s, "line", c),
                lambda: setattr(s, "fill", None),
                lambda: setattr(s, "line", None),
                lambda: s.set_alpha(0.5),
                lambda: setattr(s, "visual", Neon()),
                lambda: setattr(s, "visual", None),
                lambda: setattr(s, "glow", True),
                lambda: setattr(s, "glow", None),
            ]
        for make in kinds:
            for seed in range(6):
                a, b = self.own(make()), self.own(make())
                ra, rb = random.Random(seed), random.Random(seed)
                for _step in range(40):
                    pick = ra.randrange(10)
                    rb.randrange(10)
                    op_a = ops(a, ra)[pick]
                    op_b = ops(b, rb)[pick]
                    op_a()
                    with mock.patch.object(style_mod, "_same_plain_paint", lambda last, v: False):
                        op_b()
                    self.assertEqual(_paint_state(a), _paint_state(b),
                                     f"{type(a).__name__} seed {seed} step {_step} op {pick}")
        del rng


class TestVec2Construction(_World):
    def _general(self, x, y):
        return Vec2(x=x, y=y)       # keywords: the general path

    def test_fast_path_leaves_the_general_state(self):
        for x, y in ((1, 2), (1.5, -2.25), (0, 0.0), (10**6, -3)):
            fast, slow = Vec2(x, y), self._general(x, y)
            self.assertEqual(fast.__dict__.keys(), slow.__dict__.keys())
            for k, v in slow.__dict__.items():
                if k == "_parts":
                    self.assertEqual(list(fast.__dict__[k]), list(v))
                else:
                    self.assertEqual(fast.__dict__[k], v, k)
            self.assertIs(type(fast.x), float)
        with ephemeral_creation():
            self.assertTrue(Vec2(1.0, 2.0)._ephemeral)
        self.assertFalse(Vec2(1.0, 2.0)._ephemeral)

    def test_other_arguments_keep_the_general_rules(self):
        with self.assertRaises((TypeError, ValueError)):
            Vec2(float("nan"), 1.0)
        with self.assertRaises(TypeError):
            Vec2(True, 1.0)
        with self.assertRaises((TypeError, ValueError)):
            Vec2(10**400, 1)
        src = self.own(Circle(radius=3, center=(0, 0)))
        v = Vec2(lambda: (src.radius, 1.0))
        src.radius = 5
        self.assertEqual(v.x, 5.0)

        class Heading(Vec2):
            pass
        self.assertEqual(tuple(Heading(1, 2)), (1.0, 2.0))


class TestVelSetter(_World):
    def test_assign_writes_the_held_vector(self):
        ship = self.own(Circle(radius=5, center=(100, 100)))
        ship.vel = Vec2(1.0, 2.0)
        held = ship.vel
        ship.vel = Vec2(3.0, 4.0)
        self.assertIs(ship.vel, held)
        self.assertEqual((ship.vel.x, ship.vel.y), (3.0, 4.0))
        ship.vel = ship.vel.clamp_length(0, 2.5)
        self.assertAlmostEqual(ship.vel.length, 2.5)

    def test_a_reader_follows_the_write(self):
        ship = self.own(Circle(radius=5, center=(100, 100)))
        ship.vel = Vec2(1.0, 0.0)
        dep = self.own(Circle(radius=lambda: abs(ship.vel.x) + 1, center=(10, 10)))
        self.assertEqual(dep.radius, 2.0)
        ship.vel = Vec2(7.0, 0.0)
        self.assertEqual(dep.radius, 8.0)

    def test_bad_values_still_refuse(self):
        ship = self.own(Circle(radius=5, center=(100, 100)))
        ship.vel = (1.0, 2.0)
        bad = Vec2.temp(1.0, 2.0)
        bad.__dict__["x"] = float("inf")      # a vector holding inf (VB1-style)
        with self.assertRaises((TypeError, ValueError)):
            ship.vel = bad
        self.assertEqual((ship.vel.x, ship.vel.y), (1.0, 2.0))

    def test_destroyed_actor_refuses(self):
        from scena.entity import DestroyedError
        ship = Circle(radius=5, center=(100, 100))
        ship.vel = Vec2(1.0, 2.0)
        ship.destroy()
        with self.assertRaises(DestroyedError):
            ship.vel = Vec2(3.0, 4.0)


def _box_state(b):
    d = dict(b.__dict__)
    d["_parts"] = list(d["_parts"])
    d["_subtree_cache"] = [x is b for x in d.get("_subtree_cache", [])]
    return d


class TestMeasuredBoxFastPath(_World):
    def _both(self, *vals, name_signs=None):
        with mock.patch.object(box_mod, "_SNAPSHOT_FAST", False):
            slow = Box._snapshot(*vals, name_signs=name_signs)
        fast = Box._snapshot(*vals, name_signs=name_signs)
        return slow, fast

    def test_fast_path_leaves_the_general_state(self):
        rng = random.Random(3)
        self._both(1.0, 2.0, 3.0, 4.0, 0.0)          # captures the template
        self.assertIsNotNone(box_mod._snapshot_template)
        for _ in range(60):
            vals = (rng.uniform(-500, 500), rng.uniform(-500, 500), rng.uniform(0, 300),
                    rng.uniform(0, 300), rng.choice((0.0, rng.uniform(-180, 180))))
            ns = rng.choice((None, (1, -1)))
            slow, fast = self._both(*vals, name_signs=ns)
            self.assertEqual(_box_state(slow), _box_state(fast))
        with ephemeral_creation():
            slow, fast = self._both(1.0, 2.0, 3.0, 4.0, 0.0)
        self.assertTrue(fast._ephemeral)
        self.assertEqual(_box_state(slow), _box_state(fast))

    def test_game_view_is_fresh_and_answers_the_same(self):
        a = canvas.game_view
        a.width = 10
        b = canvas.game_view
        self.assertIsNot(a, b)
        self.assertEqual(b.width, 800.0)
        self.assertEqual((b.left, b.bottom, b.right, b.top), (0.0, 0.0, 800.0, 600.0))
        self.assertEqual(tuple(b.center), (400.0, 300.0))
        self.assertEqual(b.outset(10).width, 820.0)

    def test_values_the_general_path_rejects_skip_the_template(self):
        self._both(1.0, 2.0, 3.0, 4.0, 0.0)
        for vals in ((1, 2, 3, 4, 0), (1.0, 2.0, -3.0, 4.0, 0.0)):
            with mock.patch.object(box_mod, "_SNAPSHOT_FAST", False):
                try:
                    slow = Box._snapshot(*vals)
                except Exception as exc:        # same refusal both ways
                    with self.assertRaises(type(exc)):
                        Box._snapshot(*vals)
                    continue
            self.assertEqual(_box_state(slow), _box_state(Box._snapshot(*vals)))

    def test_a_new_system_is_not_served_the_old_template(self):
        self._both(1.0, 2.0, 3.0, 4.0, 0.0)
        tpl = box_mod._snapshot_template
        box_mod._snapshot_template = (object(),) + tpl[1:]
        try:
            b = Box._snapshot(5.0, 6.0, 7.0, 8.0, 0.0)
            self.assertIs(b._scena_system, tpl[0])
        finally:
            box_mod._snapshot_template = tpl


class TestConfineMeasuresTheOutline(_World):
    """``by="box"`` / ``"overlap"`` measure the shape's outline on the region's
    axes, for every kind (they refused a Triangle, and a rotated Circle /
    Ellipse stopped short of the wall: its frame turned with it). Full matrix
    in tests/test_confine.py (``TestOutlineEveryKind``)."""

    def test_triangle_overlap_wraps_once_it_has_left(self):
        class Passaro(Triangle, radius=9, base_ratio=0.5):
            pass
        p = self.own(Passaro(center=(100, 100)))
        p.center = (800 + 4.0, 100)              # base still on screen
        self.assertEqual(p.confine(canvas.game_view, by="overlap", action="wrap"),
                         frozenset())
        p.center = (800 + 5.0, 100)              # whole bird past the edge
        self.assertEqual(p.confine(canvas.game_view, by="overlap", action="wrap"),
                         frozenset({"right"}))
        cx, cy, r, phi0 = p._placement_params()
        self.assertLessEqual(max(x for x, _y in p._world_verts(cx, cy, r, phi0)), 0.5 + 1e-9)

    def test_rotated_circle_touches_the_wall(self):
        for ang in (0, 30, 45, 77):
            c = self.own(Circle(radius=20, center=(5, 300)))
            c.rotate_to(ang)
            c.confine(canvas.game_view, by="box")
            self.assertAlmostEqual(float(c.center.x), 20.0, msg=f"angle {ang}")

def _overlay_pixels(shape, tape: bool) -> bytes:
    surface = skia.Surface(160, 160)
    cv = surface.getCanvas()
    cv.clear(skia.ColorBLACK)
    with mock.patch.object(visuals_mod, "_geometry_tape_ok",
                           visuals_mod._geometry_tape_ok if tape else (lambda s: False)):
        shape._glow._overlay_after_filters(shape, cv)
    return bytes(surface.makeImageSnapshot().tobytes())


class TestCheapGlowBands(_World):
    KINDS = (
        lambda: Triangle(radius=20, center=(80, 80), angle=33),
        lambda: Circle(radius=20, center=(80, 80)),
        lambda: Rect(width=40, height=22, center=(80, 80), angle=20),
        lambda: Square(length=30, center=(80, 80), angle=10),
        lambda: Ellipse(width=44, height=24, center=(80, 80), angle=15),
        lambda: RegularPolygon(n=6, radius=20, center=(80, 80)),
        lambda: Polygon(points=[(60, 60), (100, 70), (80, 105)]),
        lambda: Concave(width=50, height=30, center=(80, 80), scoop='top_center'),
        lambda: Line(p1=(50, 60), p2=(110, 100)),
    )

    def test_same_pixels_as_one_draw_per_band(self):
        for make in self.KINDS:
            s = self.own(make())
            s.color = "orange"
            s.glow = CheapGlow(radius=10)
            self.assertTrue(visuals_mod._geometry_tape_ok(s), type(s).__name__)
            self.assertEqual(_overlay_pixels(s, True), _overlay_pixels(s, False),
                             type(s).__name__)

    def test_the_host_pose_is_read_once(self):
        t = self.own(Triangle(radius=20, center=(80, 80), angle=33))
        t.glow = CheapGlow()
        calls = []
        real = type(t)._geometry_draw

        def counting(self, *a, **kw):
            calls.append(1)
            return real(self, *a, **kw)
        surface = skia.Surface(160, 160)
        with mock.patch.object(type(t), "_geometry_draw", counting):
            # The patched method lives outside scena.shapes: force the tape on.
            with mock.patch.object(visuals_mod, "_geometry_tape_ok", lambda s: True):
                t._glow._overlay_after_filters(t, surface.getCanvas())
        self.assertEqual(len(calls), 1)

    def test_sprite_family_keeps_a_draw_per_band(self):
        from scena.entity import Graphic   # noqa: F401  (import check only)

        class Odd(Circle):
            def _geometry_draw(self, skia_canvas, fill_paint=None, stroke_paint=None):
                return Circle._geometry_draw(self, skia_canvas, fill_paint, stroke_paint)
        o = self.own(Odd(radius=10, center=(50, 50)))
        self.assertFalse(visuals_mod._geometry_tape_ok(o))


if __name__ == "__main__":
    unittest.main()
