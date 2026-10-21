"""Resolve partner lists stay what a fresh build gives.

Rule under test (Collision Design.md, "Resolve hot path", "Partners"): each
body's partner identities are cached across frames. The cache is dropped only
by an event that can change some list: a tag of a ``resolve()`` side gaining or
losing a member, a body named by an object side enrolling or leaving, any edit
of the pairs, and every enroll / leave while a side is ``ANYTHING`` (or another
broad side). A body that only carries other tags (a bullet in ``@collide``
pairs) enrolls and leaves without dropping anyone's list.

The oracle is a fresh build: after every operation of a random sequence, each
body's cached list must equal, in order, the list ``_resolve_partners`` builds
from scratch. ``collision._PARTNER_CACHE_SELECTIVE = False`` drops the cache on
every enroll (the old rule).

Bug class guarded: a cache invalidated too narrowly (a stale partner, a missed
newcomer, an id reused by a new collider). PF1 (Testing Design): the
``ANYTHING`` expansion (``_resolve_cache``) was cleared when a collider left but
not when one enrolled, so a partner list rebuilt by a query between two spawns
in one frame missed the second one, and kept missing it after the frame
(``TestAnythingSeesNewcomers``).
"""
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.collision import ANYTHING, STATIC, collide, get_collision_system, reset_collision_system, resolve, unresolve
from scena.shapes import Circle, Rect
from tests.floor_support import with_floor  # noqa: E402

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)

RESOLVE_TAGS = ("a", "b", "c", "d")         # sides of resolve() pairs
OTHER_TAGS = ("tiro", "gema")                # only in @collide pairs
TAGS = RESOLVE_TAGS + OTHER_TAGS


def snapshot(sys_):
    """Every body's cached partner list as (identity ids, tokens), in order."""
    out = {}
    for c in list(sys_._colliders):
        if c._part is not None:
            continue
        lst = sys_._resolve_partners(c)
        out[id(c)] = [(id(p[0]), repr(p[1])) for p in lst]
    return out


def shared_view(sys_):
    """What the resolve pass reads: each body's view of its signature's
    shared list (``_resolve_pool``), and its ``only=`` map without itself."""
    lists, onlys = {}, {}
    for c in list(sys_._colliders):
        if c._part is not None:
            continue
        lists[id(c)] = [(id(p[0]), repr(p[1])) for p in sys_._resolve_pool(c)]
        m = sys_._resolve_only_map(c) or {}
        onlys[id(c)] = {k: v for k, v in m.items() if k != id(c)}
    return lists, onlys


def fresh_only(sys_):
    sys_._partner_ident_cache.clear()
    sys_._partner_only_cache.clear()
    out = {}
    for c in list(sys_._colliders):
        if c._part is not None:
            continue
        sys_._resolve_partners(c)
        out[id(c)] = dict(sys_._partner_only_cache.get(id(c)) or {})
    return out


def fresh(sys_):
    saved = dict(sys_._partner_ident_cache), dict(sys_._partner_only_cache)
    sys_._partner_ident_cache.clear()
    sys_._partner_only_cache.clear()
    try:
        return snapshot(sys_)
    finally:
        sys_._partner_ident_cache.clear()
        sys_._partner_only_cache.clear()
        sys_._partner_ident_cache.update(saved[0])
        sys_._partner_only_cache.update(saved[1])


class SelectiveCase(unittest.TestCase):
    def setUp(self):
        reset_collision_system()
        self.owned = []

    def tearDown(self):
        for s in self.owned:
            try:
                s.destroy()
            except Exception:
                pass
        reset_collision_system()

    def body(self, r, x, tagged=True):
        # At most one resolve tag per body: two registrations reaching the
        # same body pair with different only= is an author error (raises).
        tags = []
        if tagged and r.random() < 0.8:
            tags.append(r.choice(RESOLVE_TAGS))
        if tagged and r.random() < 0.4:
            tags.append(r.choice(OTHER_TAGS))
        if r.random() < 0.5:
            s = Rect(center=(x, r.uniform(0, 200)), width=20, height=20, group=tags or None)
        else:
            s = Circle(center=(x, r.uniform(0, 200)), radius=10, group=tags or None)
        s.mass = STATIC if r.random() < 0.2 else 1.0
        self.owned.append(s)
        return s

    def run_sequence(self, seed, ops=140):
        r = random.Random(seed)
        reset_collision_system()
        sys_ = get_collision_system()
        @collide("tiro", "a")
        def _hit(t, a, info):
            pass
        literal = self.body(r, -500.0, tagged=False)
        resolve("a", "b", bounce=0.0)
        resolve("a", "a", bounce=0.0)
        resolve("c", "d", bounce=0.0, only="bottom")
        resolve(literal, "c", bounce=0.0)
        if seed % 3 == 0:
            resolve(literal, ANYTHING, bounce=0.0)
        live = [self.body(r, i * 30.0) for i in range(12)]
        sys_.step()
        checked = 0
        for k in range(ops):
            op = r.random()
            if op < 0.25 or not live:
                live.append(self.body(r, r.uniform(0, 600)))
            elif op < 0.45:
                victim = live.pop(r.randrange(len(live)))
                victim.destroy()
            elif op < 0.6:
                s = r.choice(live)
                has_resolve = any(t in RESOLVE_TAGS for t in (s.group or ()))
                s.tag(r.choice(OTHER_TAGS if has_resolve else TAGS))
            elif op < 0.72:
                s = r.choice(live)
                tags = list(s.group or ())
                if tags:
                    s.untag(r.choice(tags))
            elif op < 0.8:
                s = r.choice(live)
                s.collidable = not s.collidable
            elif op < 0.84:
                if r.random() < 0.5:
                    resolve("b", "b", bounce=0.0)
                else:
                    unresolve("b", "b")
            else:
                sys_.step()
            if k % 3 == 0:
                got = snapshot(sys_)
                want = fresh(sys_)
                self.assertEqual(got, want, f"seed {seed} op {k}: cached partner lists differ")
                # The resolve pass's shared lists (as a pool and as a list).
                for low in (8, 10_000):
                    with mock.patch.object(C, "_POOL_VECTOR_MIN", low):
                        lists, onlys = shared_view(sys_)
                    self.assertEqual(lists, want, f"seed {seed} op {k}: a shared view differs")
                self.assertEqual(onlys, fresh_only(sys_), f"seed {seed} op {k}: only= maps differ")
                checked += 1
        self.assertGreater(checked, ops // 4)


class TestCachedEqualsFresh(SelectiveCase):
    def test_random_sequences(self):
        for seed in range(12):
            self.run_sequence(seed)


@with_floor
class TestAnythingSeesNewcomers(SelectiveCase):
    """PF1: a body under resolve(hero, ANYTHING) lands on a crate spawned
    after a query in the same frame (it fell through to the floor)."""

    def fall(self, query):
        from scena.scenamath import Vec2
        reset_collision_system()
        cs = get_collision_system()
        floor = Rect(center=(0, -10), width=400, height=20, group="chao")
        floor.mass = STATIC
        floor.collidable = True
        hero = Rect(center=(0, 300), width=20, height=40, group="heroi")
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 0.0)
        self.owned += [floor, hero]
        resolve(hero, ANYTHING, bounce=0.0)
        cs.step()
        for f in range(90):
            if query:
                hero.floor_below(depth=400)
            if f == 5:
                far = Rect(center=(900, 0), width=40, height=40, group="caixa")
                far.mass = STATIC
                far.collidable = True
                if query:
                    hero.floor_below(depth=400)       # rebuilds partners: expands ANYTHING
                crate = Rect(center=(0, 100), width=80, height=40, group="caixa")
                crate.mass = STATIC
                crate.collidable = True
                self.owned += [far, crate]
                if query:
                    hero.floor_below(depth=400)       # must see the crate
            hero.vel.y -= 900.0 / 60.0
            hero.move_by(0.0, hero.vel.y / 60.0)
            cs.step()
            if "bottom" in hero.touching_sides:
                hero.vel.y = 0.0
        return float(hero.center.y) - 20.0

    def test_lands_on_the_new_crate_with_or_without_queries(self):
        self.assertAlmostEqual(self.fall(query=False), 120.0, delta=1.0)
        self.assertAlmostEqual(self.fall(query=True), 120.0, delta=1.0)


class TestUnrelatedTagsKeepTheCache(SelectiveCase):
    def test_bullet_enroll_and_leave_keep_partner_lists(self):
        sys_ = get_collision_system()
        a1 = Rect(center=(0, 0), width=20, height=20, group="a")
        a2 = Rect(center=(40, 0), width=20, height=20, group="a")
        self.owned += [a1, a2]
        resolve("a", "a", bounce=0.0)

        @collide("tiro", "a")
        def _hit(t, a, info):
            pass

        sys_.step()
        sys_._resolve_partners(C.ensure_collider(a1))
        self.assertTrue(sys_._partner_ident_cache)
        before = dict(sys_._partner_ident_cache)
        shot = Circle(center=(300, 0), radius=3, group="tiro")
        self.owned.append(shot)
        sys_.step()
        shot.destroy()
        self.assertEqual(sys_._partner_ident_cache.keys(), before.keys(),
                         "a bullet in @collide pairs only dropped the resolve partner lists")


class TestCanary(SelectiveCase):
    def test_a_shared_list_that_outlives_a_change_is_caught(self):
        real = C.CollisionSystem._invalidate_partner_cache

        def keep_shared(self_):
            shared = dict(self_._shared_pools)
            sigs = dict(self_._partner_sig_cache)
            real(self_)
            self_._shared_pools.update(shared)       # the shared lists survive
            self_._partner_sig_cache.update(sigs)

        case = TestCachedEqualsFresh("test_random_sequences")
        case.setUp()
        try:
            with mock.patch.object(C.CollisionSystem, "_invalidate_partner_cache", keep_shared):
                with self.assertRaises(AssertionError):
                    case.test_random_sequences()
        finally:
            case.tearDown()

    def test_never_invalidating_is_caught(self):
        if not hasattr(C.CollisionSystem, "_partner_cache_touched_by_tag"):
            self.skipTest("selective invalidation not present")
        with mock.patch.object(C.CollisionSystem, "_partner_cache_touched_by_tag",
                               lambda self, tag: False):
            with self.assertRaises(AssertionError):
                for seed in range(12):
                    self.run_sequence(seed)


if __name__ == "__main__":
    unittest.main()
