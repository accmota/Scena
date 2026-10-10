"""
Leave playfield: canvas.playfield, @leave_playfield, hysteresis.

Run headless:

    python -m unittest tests.test_leave_playfield -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import canvas, init, collide, leave_playfield
from scena.box import Box
from scena.bounds import _item_center_xy, get_bounds_system, reset_bounds_system
from scena.collision import get_collision_system, reset_collision_system
from scena.entity import Entity
from scena.process import every
from scena.shapes import Circle


def _bounds_step():
    get_bounds_system().step()


class LeaveBoundsTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        canvas.playfield.pad = 0.25
        reset_collision_system()
        reset_bounds_system()
        self._owned = []
        self._fired = []

    def tearDown(self):
        for s in list(self._owned):
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()
        canvas.playfield.pad = 0.25  # default; tests set explicit / inverted rects
        reset_bounds_system()
        reset_collision_system()

    def track(self, shape):
        self._owned.append(shape)
        return shape


class TestPlayfield(LeaveBoundsTestCase):
    def test_default_pad_is_one_point_five_design(self):
        b = canvas.playfield
        self.assertAlmostEqual(b.left, -250.0)
        self.assertAlmostEqual(b.bottom, -200.0)
        self.assertAlmostEqual(b.right, 1250.0)
        self.assertAlmostEqual(b.top, 1000.0)
        self.assertAlmostEqual(b.width, 1500.0)
        self.assertAlmostEqual(b.height, 1200.0)
        self.assertAlmostEqual(b.center[0], 500.0)
        self.assertAlmostEqual(b.center[1], 400.0)
        self.assertAlmostEqual(b.pad, 0.25)

    def test_set_explicit(self):
        canvas.playfield.set(left=0, bottom=0, right=1000, top=800)
        self.assertAlmostEqual(canvas.playfield.left, 0.0)
        self.assertIsNone(canvas.playfield.pad)

    def test_pad_restores_relative(self):
        canvas.playfield.set(left=0, bottom=0, right=1000, top=800)
        canvas.playfield.pad = 0.3
        self.assertAlmostEqual(canvas.playfield.left, -300.0)
        self.assertAlmostEqual(canvas.playfield.pad, 0.3)

    def test_negative_pad_shrinks_inside_design(self):
        canvas.playfield.pad = -0.1
        # design 1000×800 → extent ×0.8 → 800×640, centered
        self.assertAlmostEqual(canvas.playfield.left, 100.0)
        self.assertAlmostEqual(canvas.playfield.right, 900.0)
        self.assertAlmostEqual(canvas.playfield.bottom, 80.0)
        self.assertAlmostEqual(canvas.playfield.top, 720.0)
        self.assertAlmostEqual(canvas.playfield.pad, -0.1)

    def test_extreme_negative_pad_does_not_invert(self):
        canvas.playfield.pad = -1.0
        self.assertLessEqual(canvas.playfield.left, canvas.playfield.right)
        self.assertLessEqual(canvas.playfield.bottom, canvas.playfield.top)
        self.assertAlmostEqual(canvas.playfield.width, 0.0)
        self.assertAlmostEqual(canvas.playfield.height, 0.0)
        self.assertAlmostEqual(canvas.playfield.center[0], 500.0)
        self.assertAlmostEqual(canvas.playfield.center[1], 400.0)

    def test_invalid_set_raises(self):
        with self.assertRaises(ValueError):
            canvas.playfield.set(left=100, bottom=0, right=50, top=800)
        with self.assertRaises(ValueError):
            canvas.playfield.set(left=0, bottom=500, right=1000, top=400)


class TestSetBox(LeaveBoundsTestCase):
    """``playfield.set(box)``: the per-frame line of a camera-moves game is
    ``canvas.playfield.set(canvas.game_view.outset(m))`` (Canvas Design,
    Playfield leave bounds)."""

    def test_box_positional(self):
        canvas.playfield.set(Box._from_aabb(-10, -20, 30, 40))
        pf = canvas.playfield
        self.assertEqual((pf.left, pf.bottom, pf.right, pf.top), (-10.0, -20.0, 30.0, 40.0))
        self.assertIsNone(pf.pad)

    def test_game_view_outset_and_playfield_outset(self):
        v = canvas.game_view
        canvas.playfield.set(v.outset(300))
        self.assertAlmostEqual(canvas.playfield.left, v.left - 300)
        self.assertAlmostEqual(canvas.playfield.top, v.top + 300)
        canvas.playfield.set(canvas.playfield.outset(10))
        self.assertAlmostEqual(canvas.playfield.left, v.left - 310)

    def test_box_is_a_snapshot(self):
        b = Box._from_aabb(0, 0, 100, 100)
        canvas.playfield.set(b)
        b2 = b.outset(50)  # a new Box; the playfield keeps the old edges
        self.assertAlmostEqual(canvas.playfield.right, 100.0)
        self.assertAlmostEqual(b2.right, 150.0)

    def test_box_plus_keywords_raises(self):
        with self.assertRaisesRegex(TypeError, "not both"):
            canvas.playfield.set(Box._from_aabb(0, 0, 1, 1), left=0)

    def test_non_box_positional_names_the_keywords(self):
        for bad in ((0, 0, 100, 100), [0, 0, 100, 100], 5, "box"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(TypeError, "left=..., bottom=..., right=..., top=..."):
                    canvas.playfield.set(bad)

    def test_missing_keyword_raises(self):
        with self.assertRaisesRegex(TypeError, "missing: top"):
            canvas.playfield.set(left=0, bottom=0, right=10)
        with self.assertRaises(TypeError):
            canvas.playfield.set()

    def test_non_finite_raises(self):
        before = (canvas.playfield.left, canvas.playfield.right)
        for kw in ("left", "bottom", "right", "top"):
            edges = dict(left=0, bottom=0, right=10, top=10)
            edges[kw] = float("nan")
            with self.subTest(edge=kw):
                with self.assertRaisesRegex(ValueError, "finite"):
                    canvas.playfield.set(**edges)
        with self.assertRaisesRegex(ValueError, "finite"):
            canvas.playfield.set(Box._from_aabb(0, 0, float("inf"), 10))
        self.assertEqual((canvas.playfield.left, canvas.playfield.right), before)

    def test_inverted_box_raises(self):
        with self.assertRaises(ValueError):
            canvas.playfield.set(Box._from_aabb(10, 0, 10, 5))


class TestValidation(LeaveBoundsTestCase):
    def test_non_finite_edge_raises_at_set(self):
        for edge in ("left", "right", "bottom", "top", "pad"):
            with self.subTest(edge=edge):
                with self.assertRaises(ValueError):
                    setattr(canvas.playfield, edge, float("nan"))

    def test_edges_may_cross_between_assignments(self):
        canvas.playfield.set(left=0, bottom=0, right=900, top=800)
        canvas.playfield.left = 1000  # momentarily left > right: legal
        canvas.playfield.right = 2000
        self.assertAlmostEqual(canvas.playfield.width, 1000.0)

    def test_inverted_rect_raises_at_step(self):
        @leave_playfield("bolt")
        def gone(item):
            pass

        self.track(Circle(center=(500, 400), radius=5, group="bolt"))
        canvas.playfield.set(left=0, bottom=0, right=900, top=800)
        canvas.playfield.left = 1000  # never fixed
        with self.assertRaisesRegex(ValueError, "inverted"):
            _bounds_step()

    def test_center_validation(self):
        class P:
            def __init__(self, x, y):
                self.x, self.y = x, y

        class Item:
            def __init__(self, center):
                self.center = center

        self.assertEqual(_item_center_xy(Item(P(1, 2))), (1.0, 2.0))
        self.assertEqual(_item_center_xy(Item((3, 4))), (3.0, 4.0))
        self.assertIsNone(_item_center_xy(Item(None)))  # no pose: skipped
        with self.assertRaisesRegex(ValueError, "non-finite"):
            _item_center_xy(Item(P(float("nan"), 0)))
        with self.assertRaisesRegex(TypeError, "point or"):
            _item_center_xy(Item("bad"))
        with self.assertRaisesRegex(TypeError, "point or"):
            _item_center_xy(Item(P("bad", 0)))

    def test_bare_entity_in_group_is_skipped(self):
        @leave_playfield("dir")
        def gone(item):
            self._fired.append(item)

        self.track(Entity(group="dir"))
        _bounds_step()
        self.assertEqual(self._fired, [])


class TestSceneHandler(LeaveBoundsTestCase):
    def test_fires_once_after_inside_then_outside(self):
        @leave_playfield("bolt")
        def leftover(item):
            self._fired.append(item)

        c = self.track(Circle(center=(500, 400), radius=5, group="bolt"))
        _bounds_step()
        self.assertEqual(self._fired, [])

        c.center.y = -300
        _bounds_step()
        self.assertEqual(self._fired, [c])

        _bounds_step()
        self.assertEqual(len(self._fired), 1)

    def test_handler_error_propagates_and_consumes_the_edge(self):
        calls = []

        @leave_playfield("bolt")
        def boom(item):
            calls.append(item)
            raise RuntimeError("leave bug")

        c = self.track(Circle(center=(500, 400), radius=5, group="bolt"))
        _bounds_step()
        c.center.y = -300
        with self.assertRaisesRegex(RuntimeError, "leave bug"):
            _bounds_step()
        _bounds_step()  # still outside: does not refire
        self.assertEqual(calls, [c])

    def test_spawn_outside_does_not_fire(self):
        @leave_playfield("bolt")
        def leftover(item):
            self._fired.append(item)

        self.track(Circle(center=(500, 1100), radius=5, group="bolt"))
        _bounds_step()
        self.assertEqual(self._fired, [])

    def test_reenter_then_leave_fires_again(self):
        @leave_playfield("bolt")
        def leftover(item):
            self._fired.append(item)

        c = self.track(Circle(center=(500, 400), radius=5, group="bolt"))
        _bounds_step()
        c.center.y = -300
        _bounds_step()
        self.assertEqual(len(self._fired), 1)

        c.center.y = 400
        _bounds_step()
        c.center.y = -300
        _bounds_step()
        self.assertEqual(len(self._fired), 2)

    def test_handler_may_destroy(self):
        gone = []

        @leave_playfield("bolt")
        def leftover(item):
            gone.append(item)
            item.destroy()

        c = self.track(Circle(center=(500, 400), radius=5, group="bolt"))
        _bounds_step()
        c.center.y = -300
        _bounds_step()
        self.assertEqual(gone, [c])
        self.assertFalse(c.is_alive)

    def test_second_registration_adds(self):
        # Every top-level handler on a tag runs, like @collide and the class
        # form; before 2026-10-09 the second silently replaced the first
        # (review S4-10).
        first = []
        second = []

        @leave_playfield("bolt")
        def a(item):
            first.append(item)

        @leave_playfield("bolt")
        def b(item):
            second.append(item)

        c = self.track(Circle(center=(500, 400), radius=5, group="bolt"))
        _bounds_step()
        c.center.y = -300
        _bounds_step()
        self.assertEqual(first, [c])
        self.assertEqual(second, [c])

    def test_shared_handler_two_groups(self):
        @leave_playfield("a", "b")
        def leftover(item):
            self._fired.append(item)

        ca = self.track(Circle(center=(500, 400), radius=5, group="a"))
        cb = self.track(Circle(center=(600, 400), radius=5, group="b"))
        _bounds_step()
        ca.center.y = -300
        cb.center.y = -300
        _bounds_step()
        self.assertEqual(len(self._fired), 2)

    def test_skip_active_false(self):
        @leave_playfield("bolt")
        def leftover(item):
            self._fired.append(item)

        c = self.track(Circle(center=(500, 400), radius=5, group="bolt"))
        c.active = False
        _bounds_step()
        c.center.y = -300
        _bounds_step()
        self.assertEqual(self._fired, [])

    def test_skip_bare_entity(self):
        @leave_playfield("dir")
        def leftover(item):
            self._fired.append(item)

        self.track(Entity(group="dir"))
        _bounds_step()
        self.assertEqual(self._fired, [])


class TestClassHandler(LeaveBoundsTestCase):
    def test_class_leave_playfield(self):
        fired = []

        class Bolt(Circle):
            @leave_playfield
            def leftover(self):
                fired.append(self)
                self.destroy()

        c = self.track(Bolt(center=(500, 400), radius=5))
        _bounds_step()
        c.center.y = -300
        _bounds_step()
        self.assertEqual(len(fired), 1)
        self.assertFalse(c.is_alive)

    def test_class_handler_does_not_pin_its_actor(self):
        """S1: the registry held a bound method as a WeakKeyDictionary value —
        the value kept its own key alive, so every actor with a class
        ``@leave_playfield`` was immortal. After destroy() it is garbage."""
        import gc
        import weakref

        class Bolt(Circle):
            @leave_playfield
            def leftover(self):
                pass

        sys_ = get_bounds_system()
        c = Bolt(center=(500, 400), radius=5)
        ref = weakref.ref(c)
        _bounds_step()
        c.destroy()
        self.assertNotIn(c, sys_._instance_handlers, "destroy() must forget the handler")
        del c
        gc.collect()
        self.assertIsNone(ref(), "class @leave_playfield kept its actor alive")

    def test_every_class_handler_runs(self):
        """Two ``@leave_playfield`` methods on one class both fire (the old
        registry kept only the last one)."""
        fired = []

        class Bolt(Circle):
            @leave_playfield
            def first(self):
                fired.append("first")

            @leave_playfield
            def second(self, item):
                fired.append(("second", item is self))

        c = self.track(Bolt(center=(500, 400), radius=5))
        _bounds_step()
        c.center.y = -300
        _bounds_step()
        self.assertEqual(sorted(map(str, fired)), sorted(map(str, ["first", ("second", True)])))


class TestCollideThenLeave(LeaveBoundsTestCase):
    def test_destroyed_in_collide_skips_leave(self):
        hits = []
        leaves = []

        player = self.track(Circle(center=(500, 400), radius=20, group="player"))
        bolt = self.track(Circle(center=(500, 400), radius=5, group="bolt"))
        player.collidable = True
        bolt.collidable = True

        @collide("bolt", "player")
        def on_hit(b, p, info=None):
            hits.append(b)
            b.destroy()

        @leave_playfield("bolt")
        def leftover(item):
            leaves.append(item)

        get_collision_system().step()
        _bounds_step()
        self.assertEqual(hits, [bolt])
        self.assertEqual(leaves, [])


class TestDecoratorErrors(LeaveBoundsTestCase):
    def test_free_function_no_tags_raises(self):
        with self.assertRaises(TypeError):
            @leave_playfield
            def fn():
                pass

    def test_class_with_tags_raises(self):
        with self.assertRaises(TypeError):
            class Bad(Circle):
                @leave_playfield("bolt")
                def leftover(self):
                    pass

    def test_mix_every_raises(self):
        with self.assertRaises(TypeError):
            @every(0.5)
            @leave_playfield("bolt")
            def fn():
                pass

    def test_mix_collide_raises(self):
        a = Circle(center=(100, 100), radius=5)
        b = Circle(center=(200, 200), radius=5)
        # A signature both decorators accept: the role mix is the only fault.
        with self.assertRaisesRegex(TypeError, "@collide"):
            @collide(a, b)
            @leave_playfield("bolt")
            def fn(me, other=None, info=None):
                pass

    # Every non-name argument raises at the decorator with a fix that names
    # the right spelling (ANYTHING, group['x'] and classes are callable or
    # look like sides of @collide, so each gets its own message).
    def test_anything_raises_naming_the_alternatives(self):
        from scena import ANYTHING
        with self.assertRaisesRegex(TypeError, r"does not take ANYTHING.*bare @leave_playfield method"):
            @leave_playfield(ANYTHING)
            def fn(item):
                pass
        with self.assertRaisesRegex(TypeError, "does not take ANYTHING"):
            @leave_playfield("bolt", ANYTHING)
            def fn2(item):
                pass

    def test_group_operator_raises_with_its_name(self):
        from scena import group
        with self.assertRaisesRegex(TypeError, r"@leave_playfield\('bolt'\), not group\['bolt'\]"):
            @leave_playfield(group["bolt"])
            def fn(item):
                pass

    def test_group_operator_in_class_body_raises_with_its_name(self):
        from scena import group
        with self.assertRaisesRegex(TypeError, r"not group\['bolt'\]"):
            class Bad(Circle):
                @leave_playfield(group["bolt"])
                def out(self):
                    pass

    def test_class_raises(self):
        with self.assertRaisesRegex(TypeError, "not the class Circle"):
            @leave_playfield(Circle)
            def fn(item):
                pass

    def test_name_check_runs_before_the_function(self):
        # Bare on a class used to return the inner decorator silently.
        with self.assertRaisesRegex(TypeError, "not the class"):
            @leave_playfield
            class NotAHandler:
                pass

    def test_other_non_names_raise(self):
        actor = self.track(Circle(center=(1, 1), radius=2))
        for bad in (5, None, actor, ("bolt",)):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(TypeError, "must be strings"):
                    leave_playfield(bad)

    def test_bad_name_leaves_nothing_enrolled(self):
        with self.assertRaises(TypeError):
            @leave_playfield("bolt", 5)
            def fn(item):
                pass
        self.assertFalse(get_bounds_system().enrolled)

    # Handlers that need more arguments than Scena passes raise at the
    # decorator, like @collide — not frames later at the first leave.
    def test_script_handler_with_two_params_raises(self):
        with self.assertRaisesRegex(TypeError, r"needs 2 .* at most 1 \(item\)"):
            @leave_playfield("bolt")
            def fn(item, extra):
                pass
        self.assertFalse(get_bounds_system().enrolled)

    def test_method_with_three_params_raises(self):
        with self.assertRaisesRegex(TypeError, r"needs 3 .* at most 2 \(self, item\)"):
            class Bad(Circle):
                @leave_playfield
                def out(self, item, extra):
                    pass

    def test_accepted_signatures(self):
        @leave_playfield("bolt")
        def none():
            pass

        @leave_playfield("bolt")
        def one(item, extra=None, *, flag=False):
            pass

        @leave_playfield("bolt")
        def star(*args):
            pass

        class Ok(Circle):
            @leave_playfield
            def a(self):
                pass

            @leave_playfield
            def b(self, item):
                pass

            @leave_playfield()
            def c(self):
                pass


class TestEnrolledAndOverlay(LeaveBoundsTestCase):
    def test_not_enrolled_idle(self):
        sys = get_bounds_system()
        self.assertFalse(sys.enrolled)
        sys.step()
        sys.debug_stroke(None)

    def test_enrolled_after_decorator(self):
        @leave_playfield("bolt")
        def leftover(item):
            pass

        self.assertTrue(get_bounds_system().enrolled)


if __name__ == "__main__":
    unittest.main()
