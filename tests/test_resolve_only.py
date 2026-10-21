"""``resolve(a, b, only=...)``: one-way (jump-through) pairs.

Rule under test (Collision Design.md, "One-way pairs: only="): the pair may
only produce the listed sides of ``a`` (the words of ``a.touching_sides``). Any
other first contact makes the pair *pass*: sweep, settle and floor snap ignore
it until the two stop overlapping. S1 semantics: the side is the contact
normal at first contact, the same one a solid pair would use.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.collision import (
    STATIC,
    _RESOLVE_SLOP,
    _restore_resolve_pairs,
    collide,
    get_collision_system,
    reset_collision_system,
    resolve,
    unresolve,
)
from scena.shapes import Rect
from scena.scenamath import Vec2
from tests.floor_support import with_floor  # noqa: E402

GRAVITY = 900.0
HERO_W = 38.0
HERO_H = 70.0
PLAT_H = 16.0


class OnlyTestCase(unittest.TestCase):
    _origin = 0

    def setUp(self):
        reset_collision_system()
        self._owned = []
        OnlyTestCase._origin += 5000
        self.ox = OnlyTestCase._origin
        self.oy = OnlyTestCase._origin

    def tearDown(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_collision_system()

    # --- world -------------------------------------------------------------
    def track(self, shape):
        self._owned.append(shape)
        return shape

    def floor(self, top=0.0, group="chao"):
        f = self.track(Rect(
            center=(self.ox, self.oy + top - 20.0), width=4000.0, height=40.0,
            group=group,
        ))
        f.mass = STATIC
        return f

    def plat(self, top, x=0.0, width=200.0, group="fina", height=PLAT_H):
        p = self.track(Rect(
            center=(self.ox + x, self.oy + top - height / 2.0),
            width=width, height=height, group=group,
        ))
        p.mass = STATIC
        return p

    def hero(self, bottom, x=0.0, group="heroi"):
        h = self.track(Rect(
            center=(self.ox + x, self.oy + bottom + HERO_H / 2.0),
            width=HERO_W, height=HERO_H, group=group,
        ))
        h.mass = 1.0
        h.vel = Vec2(0.0, 0.0)
        return h

    def bottom(self, h):
        return float(h.center.y) - HERO_H / 2.0 - self.oy

    def x(self, h):
        return float(h.center.x) - self.ox

    def frame(self, h, dt=1.0 / 60.0, vx=None):
        h.vel.y -= GRAVITY * dt
        if vx is not None:
            h.vel.x = vx
        h.move_by(float(h.vel.x) * dt, float(h.vel.y) * dt)
        get_collision_system().step()

    def settle_on(self, h, frames=20, dt=1.0 / 60.0):
        for _ in range(frames):
            self.frame(h, dt)


@with_floor
class TestJumpThrough(OnlyTestCase):
    def setUp(self):
        super().setUp()
        self.floor()
        self.p = self.plat(top=128.0)
        self.h = self.hero(bottom=0.5)
        resolve("heroi", "chao", bounce=0.0)
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        self.settle_on(self.h)

    def test_jump_up_through_and_land_on_top(self):
        h = self.h
        h.vel.y = 600.0  # rise 200: feet clear the top at 128
        went_inside = False
        top_hits = 0
        for _ in range(120):
            self.frame(h)
            if "top" in h.touching_sides:
                top_hits += 1
            b = self.bottom(h)
            if b < 128.0 and b + HERO_H > 128.0 - PLAT_H:
                went_inside = True
        self.assertTrue(went_inside, "never passed through the platform")
        self.assertEqual(top_hits, 0, "head bonked a one-way platform")
        self.assertIn("bottom", h.touching_sides)
        self.assertAlmostEqual(self.bottom(h), 128.0, delta=_RESOLVE_SLOP + 0.05)
        self.assertEqual([c.other for c in h.touching_contacts], [self.p])

    def test_apex_inside_falls_back_down(self):
        """Feet never clear the top: the pass lasts until the two separate."""
        h = self.h
        h.vel.y = math.sqrt(2.0 * GRAVITY * 80.0)  # feet peak near 80 < 128
        overlapped = False
        for _ in range(120):
            self.frame(h)
            if self.bottom(h) + HERO_H > 128.0 - PLAT_H:
                overlapped = True
            for c in h.touching_contacts:
                self.assertIsNot(c.other, self.p, "stood on a platform it never cleared")
        self.assertTrue(overlapped)
        self.assertAlmostEqual(self.bottom(h), 0.0, delta=_RESOLVE_SLOP + 0.05)
        self.assertIn("bottom", h.touching_sides)

    def test_standing_is_stable_and_grounded(self):
        h = self.h
        h.vel.y = 600.0
        for _ in range(120):
            self.frame(h)
        grounded = 0
        for _ in range(120):
            self.frame(h)
            grounded += "bottom" in h.touching_sides
        self.assertEqual(grounded, 120, "grounded flickered on a one-way platform")
        self.assertAlmostEqual(self.bottom(h), 128.0, delta=_RESOLVE_SLOP + 0.05)

    def test_very_fast_jump_is_not_grounded_mid_pass(self):
        """One frame carries the head far past the underside.

        At the end of that frame the slab sits below the hero's centre, so the
        settle overlap alone reads "bottom" and would pop the hero on top while
        rising. The rejected sweep hit (the head, "top") must start the pass
        before settle runs. The body has no ``.vel``: settle then keeps the
        raw overlap axis (with ``.vel`` it would flip it to the approach).
        """
        h = self.track(Rect(
            center=(self.ox + 600.0, self.oy + 128.0 - PLAT_H - HERO_H / 2.0 - 1.0),
            width=HERO_W, height=HERO_H, group="heroi",
        ))
        self.track(Rect(
            center=(self.ox + 600.0, self.oy + 128.0 - PLAT_H / 2.0),
            width=200.0, height=PLAT_H, group="fina",
        )).mass = STATIC
        feet_below_top = []
        start = float(h.center.y)
        for i in range(1, 5):
            h.move_by(0.0, 50.0)
            get_collision_system().step()
            self.assertAlmostEqual(float(h.center.y), start + 50.0 * i, places=6)
            if float(h.center.y) - HERO_H / 2.0 - self.oy < 128.0:
                feet_below_top.append(tuple(sorted(h.touching_sides)))
        self.assertTrue(feet_below_top)
        for sides in feet_below_top:
            self.assertNotIn("bottom", sides)

    def test_collide_still_fires_while_passing(self):
        """Detection is not filtered: @collide sees the hero inside."""
        seen = []

        @collide("heroi", "fina")
        def _hit(a, b, info):
            seen.append(1)

        self.h.vel.y = 600.0
        for _ in range(60):
            self.frame(self.h)
        self.assertTrue(seen)


class TestSides(OnlyTestCase):
    def setUp(self):
        super().setUp()
        self.floor()
        # Waist-high slab: the walking hero's body spans its whole height.
        self.p = self.plat(top=40.0, x=150.0, width=100.0)
        self.h = self.hero(bottom=0.5)
        resolve("heroi", "chao", bounce=0.0)

    def walk(self, frames=90, vx=200.0):
        for _ in range(frames):
            self.frame(self.h, vx=vx)

    def test_walk_into_side_passes_through(self):
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        self.settle_on(self.h)
        self.walk()
        self.assertGreater(self.x(self.h), 150.0 + 50.0 + HERO_W / 2.0)
        self.assertNotIn("right", self.h.touching_sides)

    def test_listed_sides_block(self):
        resolve("heroi", "fina", bounce=0.0, only={"bottom", "left", "right"})
        self.settle_on(self.h)
        self.walk()
        self.assertAlmostEqual(
            self.x(self.h), 150.0 - 50.0 - HERO_W / 2.0, delta=_RESOLVE_SLOP + 0.05,
        )
        self.assertIn("right", self.h.touching_sides)

    def test_wall_behind_rejected_platform_still_blocks(self):
        """A rejected hit must not hide a real wall behind it."""
        wall = self.track(Rect(
            center=(self.ox + 230.0, self.oy + 100.0), width=20.0, height=200.0,
            group="parede",
        ))
        wall.mass = STATIC
        resolve("heroi", "parede", bounce=0.0)
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        self.settle_on(self.h)
        self.walk()
        self.assertAlmostEqual(
            self.x(self.h), 220.0 - HERO_W / 2.0, delta=_RESOLVE_SLOP + 0.05,
        )
        self.assertEqual(
            [c.other for c in self.h.touching_contacts if c.side == "right"], [wall],
        )


@with_floor
class TestFallAndDrop(OnlyTestCase):
    def test_fast_fall_does_not_tunnel(self):
        self.floor()
        p = self.plat(top=300.0)
        h = self.hero(bottom=700.0)
        resolve("heroi", "chao", bounce=0.0)
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        h.vel.y = -3000.0  # 50 per frame against a 16-thick slab
        for _ in range(30):
            self.frame(h)
        self.assertAlmostEqual(self.bottom(h), 300.0, delta=_RESOLVE_SLOP + 0.05)
        self.assertEqual([c.other for c in h.touching_contacts], [p])

    def test_drop_through_with_a_function(self):
        self.floor()
        self.plat(top=128.0)
        h = self.hero(bottom=128.5)
        state = {"drop": False}
        resolve("heroi", "chao", bounce=0.0)
        resolve("heroi", "fina", bounce=0.0,
                only=lambda c: c.side == "bottom" and not state["drop"])
        self.settle_on(h)
        self.assertAlmostEqual(self.bottom(h), 128.0, delta=_RESOLVE_SLOP + 0.05)
        state["drop"] = True
        self.frame(h)
        self.frame(h)
        # Let go while still inside: the pass holds until they separate.
        state["drop"] = False
        for _ in range(90):
            self.frame(h)
        self.assertAlmostEqual(self.bottom(h), 0.0, delta=_RESOLVE_SLOP + 0.05)

    def test_rising_platform_carries_rider(self):
        p = self.plat(top=100.0)
        h = self.hero(bottom=100.5)
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        self.settle_on(h)
        dt = 1.0 / 60.0
        for _ in range(60):
            p.move_by(0.0, 90.0 * dt)
            self.frame(h, dt)
            self.assertIn("bottom", h.touching_sides)
        top = float(p.center.y) + PLAT_H / 2.0 - self.oy
        self.assertAlmostEqual(self.bottom(h), top, delta=_RESOLVE_SLOP + 0.1)

    def test_rising_platform_into_head_passes(self):
        """A one-way platform rising into the hero's head goes through it."""
        self.floor()
        p = self.plat(top=90.0)
        h = self.hero(bottom=0.5)
        resolve("heroi", "chao", bounce=0.0)
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        self.settle_on(h)
        dt = 1.0 / 60.0
        for _ in range(120):
            p.move_by(0.0, 60.0 * dt)
            self.frame(h, dt)
            self.assertNotIn("top", h.touching_sides)
        self.assertAlmostEqual(self.bottom(h), 0.0, delta=_RESOLVE_SLOP + 0.05)

    def test_growing_into_underside_passes(self):
        """A size change is not swept; unswept recovery must ask only= too."""
        p = self.plat(top=90.0)
        h = self.hero(bottom=0.0)  # head at 70, underside at 74
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        cs = get_collision_system()
        cs.step()
        h.height = HERO_H + 16.0  # head crosses 4 into the underside
        start = float(h.center.y)
        for _ in range(3):
            cs.step()
            self.assertNotIn("top", h.touching_sides)
        self.assertEqual(float(h.center.y), start)
        self.assertIs(cs._passing[id(h._collider)][id(p._collider)], p._collider)

    def test_spawned_under_platform_is_not_pushed(self):
        """A rejected overlap in settle starts a pass (no push)."""
        p = self.plat(top=128.0)
        # Head 6 into the underside: the shallow axis is the hero's top.
        h = self.hero(bottom=128.0 - PLAT_H - HERO_H + 6.0)
        resolve("heroi", "fina", only="bottom")
        start = float(h.center.y)
        get_collision_system().step()
        self.assertEqual(float(h.center.y), start)
        cs = get_collision_system()
        self.assertIs(cs._passing[id(h._collider)][id(p._collider)], p._collider)


@with_floor
class TestTileSeams(OnlyTestCase):
    """Walking across a row of one-way tiles must never drop through a seam."""

    def run_row(self, fps):
        dt = 1.0 / fps
        tiles = [self.plat(top=100.0, x=-60.0 + 40.0 * i, width=40.0) for i in range(8)]
        h = self.hero(bottom=100.5, x=-60.0)
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        self.settle_on(h, frames=int(fps // 3), dt=dt)
        right_edge = -60.0 + 40.0 * 7 + 20.0
        while self.x(h) < right_edge - HERO_W:
            self.frame(h, dt, vx=150.0)
            self.assertIn("bottom", h.touching_sides, f"seam drop at x={self.x(h):.2f}")
            self.assertGreater(self.bottom(h), 100.0 - 1.0)
        return tiles

    def test_seams_30fps(self):
        self.run_row(30)

    def test_seams_60fps(self):
        self.run_row(60)

    def test_seams_240fps(self):
        self.run_row(240)


@with_floor
class TestPerspective(OnlyTestCase):
    def test_function_sees_first_argument_view(self):
        p = self.plat(top=100.0)
        h = self.hero(bottom=140.0)
        seen = []

        def only(c):
            seen.append(c)
            return c.side == "bottom"

        resolve("heroi", "fina", bounce=0.0, only=only)
        self.settle_on(h, frames=40)
        self.assertTrue(seen)
        c = seen[-1]
        self.assertEqual(c.side, "bottom")
        self.assertIs(c.other, p)
        self.assertAlmostEqual(float(c.normal.y), -1.0, places=6)

    def test_function_with_body_second_is_flipped(self):
        """``resolve("fina", "heroi", only=f)``: f sees the platform's view."""
        p = self.plat(top=100.0)
        h = self.hero(bottom=140.0)
        seen = []

        def only(c):
            seen.append(c)
            return c.side == "top"

        resolve("fina", "heroi", bounce=0.0, only=only)
        self.settle_on(h, frames=40)
        self.assertTrue(seen)
        self.assertEqual(seen[-1].side, "top")
        self.assertIs(seen[-1].other, h)
        self.assertAlmostEqual(self.bottom(h), 100.0, delta=_RESOLVE_SLOP + 0.05)

    def test_set_with_body_second_is_mirrored(self):
        self.plat(top=100.0)
        h = self.hero(bottom=140.0)
        resolve("fina", "heroi", bounce=0.0, only="top")
        self.settle_on(h, frames=40)
        self.assertIn("bottom", h.touching_sides)
        self.assertAlmostEqual(self.bottom(h), 100.0, delta=_RESOLVE_SLOP + 0.05)

    def test_two_moving_bodies(self):
        """A dynamic first argument: B lands on A only from above A's view."""
        self.floor()
        a = self.hero(bottom=0.5, group="caixa_a")
        b = self.hero(bottom=200.0, group="caixa_b")
        resolve(["caixa_a", "caixa_b"], "chao", bounce=0.0)
        # From A's view only its "bottom": B falling on A's top passes through.
        resolve("caixa_a", "caixa_b", bounce=0.0, only="bottom")
        for _ in range(120):
            a.vel.y -= GRAVITY / 60.0
            a.move_by(0.0, float(a.vel.y) / 60.0)
            self.frame(b)
        self.assertAlmostEqual(self.bottom(b), 0.0, delta=_RESOLVE_SLOP + 0.05)
        self.assertAlmostEqual(self.bottom(a), 0.0, delta=_RESOLVE_SLOP + 0.05)


class TestValidation(OnlyTestCase):
    def only_of(self):
        (pair,) = get_collision_system()._resolve_pairs
        return pair[3]

    def test_collections_are_or(self):
        self.plat(top=0.0)
        self.hero(bottom=100.0)
        for value in (("bottom", "left"), ["left", "bottom"], {"bottom", "left"},
                      frozenset({"left", "bottom"})):
            resolve("heroi", "fina", only=value)
            self.assertEqual(self.only_of(), frozenset({"bottom", "left"}))
        resolve("heroi", "fina", only=("bottom"))  # a string in parentheses
        self.assertEqual(self.only_of(), frozenset({"bottom"}))

    def test_all_four_sides_is_no_filter(self):
        self.plat(top=0.0)
        self.hero(bottom=100.0)
        resolve("heroi", "fina", only=["top", "bottom", "left", "right"])
        self.assertIsNone(self.only_of())
        self.assertFalse(get_collision_system()._has_only)

    def test_bad_values(self):
        self.plat(top=0.0)
        self.hero(bottom=100.0)
        with self.assertRaisesRegex(ValueError, 'Did you mean "bottom"'):
            resolve("heroi", "fina", only="floor")
        with self.assertRaisesRegex(ValueError, 'Did you mean "top"'):
            resolve("heroi", "fina", only="ceiling")
        with self.assertRaisesRegex(ValueError, "use a set"):
            resolve("heroi", "fina", only="bottom, left")
        with self.assertRaisesRegex(ValueError, "is not a side"):
            resolve("heroi", "fina", only="up")
        with self.assertRaisesRegex(ValueError, "unresolve"):
            resolve("heroi", "fina", only=[])
        with self.assertRaises(TypeError):
            resolve("heroi", "fina", only=5)
        with self.assertRaises(TypeError):
            resolve("heroi", "fina", only=["bottom", 1])
        # Nothing half-registered.
        self.assertEqual(get_collision_system()._resolve_pairs, [])

    def test_self_pair_needs_a_mirror_symmetric_set(self):
        self.hero(bottom=0.0, group="caixa")
        with self.assertRaisesRegex(ValueError, "against itself"):
            resolve("caixa", "caixa", only="bottom")
        self.assertEqual(get_collision_system()._resolve_pairs, [])
        resolve("caixa", "caixa", only={"top", "bottom"})
        resolve("caixa", "caixa", only=lambda c: True)

    def test_re_register_replaces_only_last_call_wins(self):
        self.plat(top=0.0)
        self.hero(bottom=100.0)
        resolve("heroi", "fina", only="bottom")
        self.assertTrue(get_collision_system()._has_only)
        resolve("heroi", "fina")
        self.assertIsNone(self.only_of())
        self.assertFalse(get_collision_system()._has_only)
        resolve("fina", "heroi", only="top")
        a, b, _tok, only = get_collision_system()._resolve_pairs[0]
        self.assertEqual((a, b, only), ("fina", "heroi", frozenset({"top"})))

    def test_destroy_mid_pass_leaves_no_state(self):
        p = self.plat(top=128.0)
        h = self.hero(bottom=128.0 - PLAT_H - HERO_H + 6.0)
        resolve("heroi", "fina", only="bottom")
        cs = get_collision_system()
        cs.step()
        self.assertTrue(cs._passing)
        p.destroy()
        cs.step()
        cs.step()
        self.assertEqual(cs._passing, {})
        h.destroy()
        cs.step()
        self.assertEqual(cs._passing, {})

    def test_unresolve_clears_passing_state(self):
        self.plat(top=128.0)
        h = self.hero(bottom=128.0 - PLAT_H - HERO_H + 6.0)
        resolve("heroi", "fina", only="bottom")
        get_collision_system().step()
        self.assertTrue(get_collision_system()._passing)
        unresolve("heroi", "fina")
        self.assertFalse(get_collision_system()._has_only)
        self.assertFalse(get_collision_system()._passing)
        self.assertIsNotNone(h)


# Module-level values the purity tests close over (the static pass resolves
# names through the function's globals, like @= formulas).
_CACHE = {}
_LOG = []


def _helper_that_destroys(c):
    c.other.destroy()
    return True


def _helper_that_reads(c):
    return c.side == "bottom"


class _Rules:
    """An author object: its methods are followed by the static pass."""

    def __init__(self):
        self.calls = 0

    def lands(self, c):
        self.calls += 1  # the author's own object, not Scena
        return c.side == "bottom"


class _CallableObject:
    """No readable code for the static pass: only the runtime lock sees it."""

    def __init__(self, action):
        self.action = action

    def __call__(self, c):
        self.action(c)
        return True


class TestOnlyPurityStatic(OnlyTestCase):
    """``only=`` functions are read at ``resolve()`` and refused if they write."""

    def setUp(self):
        super().setUp()
        self.p = self.plat(top=0.0)
        self.h = self.hero(bottom=100.0)

    def refused(self, fn, pattern):
        with self.assertRaisesRegex(TypeError, pattern):
            resolve("heroi", "fina", only=fn)
        self.assertEqual(get_collision_system()._resolve_pairs, [])

    def test_writes_to_scena_objects_refuse(self):
        from scena import st
        h = self.h

        def writes_st(c):
            st.pousou = True
            return True

        def writes_vel(c):
            h.vel.y = 0.0
            return True

        def aliases(c):
            alvo = h
            alvo.width = 10.0
            return True

        def links(c):
            h["width"] @= lambda: 3.0
            return True

        self.refused(writes_st, r"writes st\.pousou")
        self.refused(writes_vel, r"writes h\.vel\.y")
        self.refused(aliases, r"writes alvo\.width")
        self.refused(links, "links")
        self.refused(lambda c: setattr(h, "width", 3.0), r"calls setattr\(\)")

    def test_scena_verbs_refuse(self):
        from scena import Rect as _Rect, chance, keyp, recently
        h = self.h
        self.refused(lambda c: c.other.destroy(), r"calls c\.other\.destroy\(\)")
        self.refused(lambda c: h.move_by(0, 1) or True, r"calls h\.move_by\(\)")
        self.refused(lambda c: recently("x", True), r"calls recently\(\)")
        self.refused(lambda c: chance(0.5), r"calls chance\(\)")
        self.refused(lambda c: keyp.once("UP"), r"calls keyp\.once\(\)")
        self.refused(lambda c: _Rect(center=(0, 0), width=1, height=1) is None,
                     "creates a Rect")

    def test_global_and_helpers_refuse(self):
        def uses_global(c):
            global _CACHE
            return True

        self.refused(uses_global, "global/nonlocal")
        self.refused(lambda c: _helper_that_destroys(c),
                     r"in _helper_that_destroys\(\).*calls c\.other\.destroy")

    def test_reads_and_own_objects_are_allowed(self):
        from scena import Vec2 as _Vec2, keyp

        def own_local(c):
            memo = {}
            memo["side"] = c.side
            n = _Vec2(0.0, -1.0)
            return memo["side"] == "bottom" and c.normal.dot(n) > 0.5

        def own_module_objects(c):
            _CACHE[c.side] = True
            _LOG.append(c.side)
            print_ok = len(_LOG) >= 0
            return print_ok and c.side == "bottom"

        rules = _Rules()
        for fn in (
            lambda c: c.side == "bottom" and not keyp("DOWN"),
            own_local,
            own_module_objects,
            _helper_that_reads,
            lambda c: _helper_that_reads(c),
            rules.lands,
            lambda c: rules.lands(c),
            lambda c: self.h.collides_with("fina") is not None or True,
        ):
            with self.subTest(fn=fn):
                resolve("heroi", "fina", only=fn)


class TestOnlyPurityRuntime(OnlyTestCase):
    """What the static pass cannot read still hits the solver lock."""

    def setUp(self):
        super().setUp()
        self.p = self.plat(top=100.0)
        self.h = self.hero(bottom=110.0)

    def refused_at_step(self, action, pattern):
        from scena.purity_check import _READING
        resolve("heroi", "fina", bounce=0.0, only=_CallableObject(action))
        with self.assertRaisesRegex(RuntimeError, pattern):
            for _ in range(30):
                self.frame(self.h)
        self.assertEqual(_READING, [], "the lock must be released after a refusal")

    def test_destroy(self):
        self.refused_at_step(lambda c: c.other.destroy(), r"destroy\(\) ran inside")

    def test_state_write(self):
        from scena import st

        def act(c):
            st.only_purity_probe = 1

        self.refused_at_step(act, r"st\.only_purity_probe = … ran inside")

    def test_spawn(self):
        self.refused_at_step(lambda c: Rect(center=(0, 0), width=1, height=1),
                             "creating a Rect ran inside")

    def test_schedule_and_polls(self):
        from scena import after, keyp, recently
        self.refused_at_step(lambda c: after(1.0, lambda: None), r"after\(\) ran inside")
        self.tearDown()
        self.setUp()
        self.refused_at_step(lambda c: recently("x", True), r"recently\(\) ran inside")
        self.tearDown()
        self.setUp()
        self.refused_at_step(lambda c: keyp.once("UP"), r"keyp\.once\(\) ran inside")

    def test_collision_registrations(self):
        self.refused_at_step(lambda c: resolve("heroi", "chao"), r"resolve\(\) ran inside")
        self.tearDown()
        self.setUp()
        self.refused_at_step(lambda c: c.other.tag("outro"), "a group change")

    def test_message_names_the_function(self):
        resolve("heroi", "fina", bounce=0.0,
                only=_CallableObject(lambda c: c.other.destroy()))
        with self.assertRaisesRegex(RuntimeError, r"only=_CallableObject"):
            for _ in range(30):
                self.frame(self.h)

    def test_reads_run_unlocked_after_the_step(self):
        """The lock is scoped to the call: normal writes work between frames."""
        from scena import st
        resolve("heroi", "fina", bounce=0.0, only=lambda c: c.side == "bottom")
        for _ in range(20):
            self.frame(self.h)
        st.only_purity_after = 1  # no refusal outside the solver
        self.assertIn("bottom", self.h.touching_sides)


class TestConflicts(OnlyTestCase):
    def test_two_registrations_disagree_raises_and_rolls_back(self):
        self.plat(top=0.0, group="plataforma").tag("fina")
        self.hero(bottom=100.0)
        resolve("heroi", "plataforma", bounce=0.0)
        before = list(get_collision_system()._resolve_pairs)
        with self.assertRaisesRegex(ValueError, "disagree on only="):
            resolve("heroi", "fina", bounce=0.0, only="bottom")
        self.assertEqual(get_collision_system()._resolve_pairs, before)
        self.assertFalse(get_collision_system()._has_only)

    def test_same_only_twice_is_fine(self):
        self.plat(top=0.0, group="fina").tag("fina2")
        self.hero(bottom=100.0)
        resolve("heroi", "fina", only="bottom")
        resolve("heroi", "fina2", only=["bottom"])

    def test_late_tag_join_raises_on_step(self):
        p = self.plat(top=0.0)
        self.plat(top=0.0, x=500.0, group="plataforma")
        self.hero(bottom=100.0)
        resolve("heroi", "plataforma", bounce=0.0)
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        get_collision_system().step()
        p.tag("plataforma")
        with self.assertRaisesRegex(ValueError, "disagree on only="):
            get_collision_system().step()


class TestSceneRestore(OnlyTestCase):
    def test_restore_brings_back_only(self):
        self.plat(top=0.0)
        self.hero(bottom=100.0)
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        snapshot = list(get_collision_system()._resolve_pairs)
        unresolve("heroi", "fina")
        resolve("heroi", "fina", bounce=0.0)  # an act re-tunes it
        _restore_resolve_pairs(snapshot)
        self.assertEqual(get_collision_system()._resolve_pairs, snapshot)
        self.assertTrue(get_collision_system()._has_only)


class TestUnfilteredUnchanged(OnlyTestCase):
    """Bug-class guard: a pair without only= behaves the same whether or not
    some other pair in the world has one (the gate never touches it)."""

    def trajectory(self, with_other_only):
        reset_collision_system()
        for s in self._owned:
            s.destroy()
        self._owned.clear()
        self.floor()
        self.plat(top=60.0, x=120.0, width=80.0, group="bloco")
        h = self.hero(bottom=150.0, x=40.0)
        resolve("heroi", ["chao", "bloco"], bounce=0.0)
        if with_other_only:
            self.plat(top=300.0, x=2000.0, group="fina")
            self.hero(bottom=400.0, x=2000.0, group="outro")
            resolve("outro", "fina", bounce=0.0, only="bottom")
        path = []
        for i in range(150):
            self.frame(h, vx=120.0 if i < 100 else -80.0)
            path.append((float(h.center.x), float(h.center.y),
                         tuple(sorted(h.touching_sides))))
        return path

    def test_same_path_with_and_without_other_only(self):
        self.assertEqual(self.trajectory(False), self.trajectory(True))

    def test_no_gate_state_without_only(self):
        self.floor()
        h = self.hero(bottom=10.0)
        resolve("heroi", "chao", bounce=0.0)
        self.settle_on(h)
        cs = get_collision_system()
        self.assertFalse(cs._has_only)
        self.assertFalse(cs._partner_only_cache.get(id(h._collider)))
        self.assertFalse(cs._passing)


if __name__ == "__main__":
    unittest.main()
