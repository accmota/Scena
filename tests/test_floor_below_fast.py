"""``floor_below``'s march fast path agrees with the plain march.

Rule under test (Collision Design.md, "Floor ahead: floor_below", "Cost"):
two reductions that must not change any answer —

* the march trusts each partner's world prims while it runs: the partners'
  proxies were refreshed at the start of the call and nothing moves a body
  until it returns (the narrow and resolve passes rely on the same window);
* partners whose fresh proxy misses the march envelope (the probe, the whole
  ``dx``, the most every sub-step can lift and drop) are dropped once, before
  the casts, instead of being re-tested by each of the up to 15 casts.

``collision._FLOOR_PROBE_FAST`` switches both off (the plain march, kept as
the oracle and for the bench A/B). Each randomized scene asks the same
question both ways and compares the floor found and the probe's end pose.

Bug class guarded: a fast path that drops a partner a cast could reach (too
small an envelope), or that answers from prims built before the partner moved.
"""
import math
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.collision import STATIC, get_collision_system, reset_collision_system, resolve
collision = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
from scena.shapes import Circle, Polygon, Rect

CASES = 160


class _Scene:
    """A random strip of ground around x = 0 (world offset ``o``)."""

    def __init__(self, rng, o):
        self.rng = rng
        self.o = o
        self.owned = []
        self.ground = []

    def add(self, shape, group="chao"):
        shape.mass = STATIC
        self.owned.append(shape)
        self.ground.append(shape)
        return shape

    def build(self):
        r, o = self.rng, self.o
        x = -260.0
        top = 0.0
        while x < 260.0:
            kind = r.random()
            w = r.choice((16.0, 32.0, 48.0, 64.0))
            if kind < 0.12:                      # a gap
                x += r.choice((8.0, 24.0, 40.0))
                continue
            if kind < 0.25:                      # a slope (polygon) up or down
                rise = r.choice((-24.0, -12.0, 12.0, 24.0, 40.0))
                pts = [(x, top - 30.0), (x + w, top - 30.0), (x + w, top + rise), (x, top)]
                self.add(Polygon(points=[(o + px, o + py) for px, py in pts], group="chao"))
                top += rise
                x += w
                continue
            if kind < 0.35:                      # a step
                top += r.choice((-20.0, -8.0, 6.0, 14.0, 30.0))
            h = r.choice((8.0, 20.0, 40.0))
            self.add(Rect(center=(o + x + w / 2.0, o + top - h / 2.0), width=w, height=h,
                          group="chao"))
            x += w
        for _ in range(r.randint(0, 3)):         # one-way platforms and ceilings
            cx = r.uniform(-200.0, 200.0)
            cy = r.uniform(20.0, 90.0)
            grp = "fina" if r.random() < 0.5 else "chao"
            self.add(Rect(center=(o + cx, o + cy), width=r.choice((40.0, 80.0)), height=6.0,
                          group=grp))
        if r.random() < 0.3:                     # a wall
            wx = r.uniform(-150.0, 150.0)
            self.add(Rect(center=(o + wx, o + 40.0), width=12.0, height=120.0, group="chao"))

    def hero(self):
        r, o = self.rng, self.o
        x = r.uniform(-180.0, 180.0)
        y = r.uniform(-40.0, 60.0)
        if r.random() < 0.3:
            h = Circle(center=(o + x, o + y + 12.5), radius=r.choice((8.0, 12.0)), group="heroi")
        else:
            h = Rect(center=(o + x, o + y + 20.5), width=r.choice((14.0, 20.0, 30.0)),
                     height=r.choice((24.0, 40.0)), group="heroi")
        h.mass = 1.0
        self.owned.append(h)
        return h

    def destroy(self):
        for s in self.owned:
            try:
                s.destroy()
            except Exception:
                pass


def _probe_pose(captured):
    prims, found = captured
    xs0 = min(p.aabb[0] for p in prims)
    ys0 = min(p.aabb[1] for p in prims)
    return (round(xs0, 6), round(ys0, 6), found)


class FastCase(unittest.TestCase):
    _origin = 0

    def setUp(self):
        reset_collision_system()
        FastCase._origin += 4000
        self.o = float(FastCase._origin)
        self.scenes = []

    def tearDown(self):
        for s in self.scenes:
            s.destroy()
        reset_collision_system()

    def ask(self, h, fast, **kw):
        """``floor_below`` with the switch set; returns (floor, end pose)."""
        seen = []
        real = collision.CollisionSystem._note_floor_probe

        def note(sys_, body, prims, found):
            seen.append((list(prims), found))
            return real(sys_, body, prims, found)

        with mock.patch.object(collision, "_FLOOR_PROBE_FAST", fast, create=True), \
                mock.patch.object(collision.CollisionSystem, "_note_floor_probe", note):
            got = h.floor_below(**kw)
        pose = _probe_pose(seen[-1]) if seen and seen[-1][0] else None
        return got, pose

    def scene(self, seed):
        sc = _Scene(random.Random(seed), self.o)
        sc.build()
        self.scenes.append(sc)
        return sc


class TestFastMarchAgrees(FastCase):
    def test_random_scenes_answer_the_same(self):
        compared = 0
        for seed in range(CASES):
            reset_collision_system()
            sc = self.scene(seed)
            h = sc.hero()
            use_group = sc.rng.random() < 0.5
            if use_group:
                groups = ["chao", "fina"]
                kw_ground = {"group": groups}
            else:
                resolve("heroi", "chao", bounce=0.0)
                resolve("heroi", "fina", bounce=0.0, only="bottom")
                kw_ground = {}
            for _ in range(4):
                dx = sc.rng.choice((0.0, 3.0, -9.0, 16.0, -40.0, 47.5, 120.0, -200.0))
                depth = sc.rng.choice((None, None, 4.0, 40.0))
                kw = dict(kw_ground, dx=dx)
                if depth is not None:
                    kw["depth"] = depth
                slow = self.ask(h, False, **kw)
                fast = self.ask(h, True, **kw)
                self.assertIs(fast[0], slow[0], f"seed {seed} {kw}: floor differs")
                self.assertEqual(fast[1], slow[1], f"seed {seed} {kw}: end pose differs")
                compared += 1
            sc.destroy()
            self.scenes.remove(sc)
        self.assertGreaterEqual(compared, CASES * 4)

    def test_answers_are_not_all_none(self):
        """No vacuous pass: the scenes must find floors and ledges both."""
        found = missed = 0
        for seed in range(40):
            reset_collision_system()
            sc = self.scene(seed)
            h = sc.hero()
            got, _ = self.ask(h, True, dx=24.0, group="chao")
            if got is None:
                missed += 1
            else:
                found += 1
            sc.destroy()
            self.scenes.remove(sc)
        self.assertGreater(found, 5)
        self.assertGreater(missed, 5)


class TestFastMarchSeesMoves(FastCase):
    """A partner moved by plain assignment just before the call is seen."""

    def test_tile_moved_in_or_out_is_seen(self):
        o = self.o
        floor = Rect(center=(o, o - 10.0), width=200.0, height=20.0, group="chao")
        floor.mass = STATIC
        tile = Rect(center=(o + 300.0, o - 10.0), width=60.0, height=20.0, group="chao")
        tile.mass = STATIC
        h = Rect(center=(o + 90.0, o + 20.5), width=20.0, height=40.0, group="heroi")
        h.mass = 1.0
        self.scenes.append(type("S", (), {"destroy": lambda self_: [s.destroy() for s in
                                                                     (floor, tile, h)]})())
        get_collision_system().step()
        for fast in (False, True):
            tile.center = (o + 300.0, o - 10.0)
            self.assertIsNone(self.ask(h, fast, dx=40.0, group="chao")[0], f"fast={fast}")
            tile.center = (o + 130.0, o - 10.0)        # placement, no step()
            self.assertIs(self.ask(h, fast, dx=40.0, group="chao")[0], tile, f"fast={fast}")
            tile.width = 10.0                          # a resize, still no step()
            tile.center = (o + 150.0, o - 10.0)
            self.assertIsNone(self.ask(h, fast, dx=40.0, group="chao")[0], f"fast={fast}")
            tile.width = 60.0


class TestCanaries(FastCase):
    """The checks above must be able to fail."""

    def test_too_small_envelope_is_caught(self):
        if not hasattr(collision, "_floor_probe_envelope"):
            self.skipTest("fast path not present")

        def tiny(pas, dx, step_max, reach):
            minx = min(p.aabb[0] for p in pas)
            miny = min(p.aabb[1] for p in pas)
            maxx = max(p.aabb[2] for p in pas)
            maxy = max(p.aabb[3] for p in pas)
            return (minx, miny, maxx, maxy)     # no march at all

        case = TestFastMarchAgrees("test_random_scenes_answer_the_same")
        case.setUp()
        try:
            with mock.patch.object(collision, "_floor_probe_envelope", tiny):
                with self.assertRaises(AssertionError):
                    case.test_random_scenes_answer_the_same()
        finally:
            case.tearDown()

    def test_stale_prims_are_caught(self):
        if not hasattr(collision, "_floor_probe_envelope"):
            self.skipTest("fast path not present")
        real = collision.CollisionSystem._update_proxy

        def no_refresh(self_, c, commit_motion=True):
            if not c._proxy_valid:
                return real(self_, c, commit_motion=commit_motion)
            return True                          # trust whatever is there

        case = TestFastMarchSeesMoves("test_tile_moved_in_or_out_is_seen")
        case.setUp()
        try:
            with mock.patch.object(collision.CollisionSystem, "_update_proxy", no_refresh):
                with self.assertRaises(AssertionError):
                    case.test_tile_moved_in_or_out_is_seen()
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
