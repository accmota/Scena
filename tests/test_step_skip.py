"""The step's skips for still bodies change no answer.

Rule under test (Collision Design.md, "Step cost"): ``step()`` keeps a resolve
collider's stored bounds (``_resolved_aabb``, read by next frame's unswept
recovery) while its pose key is the same object, and publishes ``touching_*``
only to bodies that touch something now or did at the last publish (every
other body already reads empty). ``collision._STEP_SKIP_STILL = False`` is the
full walk (the oracle).

Random scenes (walkers on tiles, a moving platform, a pushing crowd, spawns,
destroys, placements, a body leaving and rejoining collision; and
the order ``touching_sides`` changes are written in) run with the switch on
and off and give the same frames: positions, sides, contacts, stored bounds
and the same sequence of changes. After every step the stored bounds equal fresh ones and
no unvisited body reads a contact.

Bug class guarded: a cached per-body answer that outlives the pose or contact
it was made from.
"""
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena.collision import STATIC, get_collision_system, reset_collision_system, resolve
from scena.scenamath import Vec2
from scena.shapes import Circle, Rect

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
DT = 1.0 / 60.0


class Scene:
    def __init__(self, seed, origin, log):
        self.r = random.Random(seed)
        self.o = origin
        self.log = log
        self.owned = []

    def keep(self, s, mass):
        s.mass = mass
        if mass != STATIC:
            s.vel = Vec2(0.0, 0.0)
        self.owned.append(s)
        return s

    def build(self):
        r, o = self.r, self.o
        x = 0.0
        while x < 1200.0:
            w = r.choice((40.0, 80.0))
            if r.random() > 0.1:
                self.keep(Rect(center=(o + x + w / 2, o - 10.0), width=w, height=20.0,
                               group="chao"), STATIC)
            x += w
        self.lift = self.keep(Rect(center=(o + 300.0, o + 60.0), width=100.0, height=10.0,
                                   group="chao"), STATIC)
        self.walkers = [self.keep(Rect(center=(o + 60.0 + 100.0 * i, o + 120.0), width=18.0,
                                       height=30.0, group="robo"), 1.0) for i in range(8)]
        self.crowd = [self.keep(Circle(center=(o + r.uniform(0, 1100), o + r.uniform(20, 200)),
                                       radius=r.uniform(6, 12), group="bola"), 1.0)
                      for _ in range(20)]
        resolve("robo", "chao", bounce=0.0)
        resolve("bola", "chao", bounce=0.0)
        resolve("bola", "bola", bounce=0.0)

    def frame(self, f):
        r, o = self.r, self.o
        self.lift.move_by(0.0, 40.0 * DT * (1 if (f // 40) % 2 == 0 else -1))
        for i, w in enumerate(self.walkers):
            if "bottom" in w.touching_sides and r.random() < 0.05:
                w.vel.y = 380.0
            w.vel.x = 120.0 if i % 2 == 0 else -120.0
            w.vel.y -= 1200.0 * DT
            w.move_by(w.vel.x * DT, w.vel.y * DT)
        for b in self.crowd:
            b.vel.y -= 900.0 * DT
            b.move_by(r.uniform(-1, 1), b.vel.y * DT)
        if f % 25 == 12:
            b = self.crowd.pop(r.randrange(len(self.crowd)))
            b.destroy()
            self.crowd.append(self.keep(Circle(center=(o + r.uniform(0, 1100), o + 220.0),
                                               radius=8.0, group="bola"), 1.0))
        if f % 30 == 20:
            w = r.choice(self.walkers)
            w.center = (o + r.uniform(0, 1100), o + 150.0)             # placement
        if f % 45 == 30:
            w = self.walkers[f % len(self.walkers)]
            w.collidable = not w.collidable                            # leaves / rejoins
        cs = get_collision_system()
        cs.step()
        for w in self.walkers + self.crowd:
            if "bottom" in w.touching_sides and w.vel.y < 0.0:
                w.vel.y = 0.0
        out = []
        for s in self.walkers + self.crowd:
            out.append((round(float(s.center.x), 9), round(float(s.center.y), 9),
                        tuple(sorted(s.touching_sides)), len(s.touching_contacts)))
        out.append(tuple(c._resolved_aabb for c in cs._colliders))
        return out

    def destroy(self):
        for s in self.owned:
            try:
                s.destroy()
            except Exception:
                pass
        self.owned.clear()


def check_invariants(tc, ctx):
    cs = get_collision_system()
    for c in cs._colliders:
        if c._in_resolve:
            fresh = cs._exact_bounds_aabb(c)
            tc.assertIsNotNone(c._resolved_aabb, ctx)
            for a, b in zip(c._resolved_aabb, fresh):
                tc.assertAlmostEqual(a, b, delta=1e-6, msg=f"{ctx}: stale stored bounds")
        ident = c._identity
        if id(c) not in cs._touching_live and c._part is None and hasattr(ident, "touching_sides"):
            tc.assertFalse(ident.touching_sides, f"{ctx}: an unvisited body reads a contact")


class TestSameFrames(unittest.TestCase):
    def run_scene(self, seed, on, frames=150, check=False):
        reset_collision_system()
        log = []
        sc = Scene(seed, 30000.0 + 4000.0 * seed, log)
        trace = []
        from scena.entity import Graphic
        real = Graphic._collision_set_touching

        def logged(ident, sides, contacts):
            if ident.touching_sides != sides:
                log.append((sc.owned.index(ident) if ident in sc.owned else -1,
                            tuple(sorted(sides))))
            return real(ident, sides, contacts)

        try:
            with mock.patch.object(C, "_STEP_SKIP_STILL", on), \
                    mock.patch.object(Graphic, "_collision_set_touching", logged):
                sc.build()
                for f in range(frames):
                    trace.append(sc.frame(f))
                    if check:
                        check_invariants(self, f"seed {seed} frame {f}")
        finally:
            sc.destroy()
            reset_collision_system()
        return trace, log

    def test_same_frames_and_hooks(self):
        touched = 0
        for seed in range(3):
            a, la = self.run_scene(seed, False)
            b, lb = self.run_scene(seed, True)
            for f, (fa, fb) in enumerate(zip(a, b)):
                self.assertEqual(fa, fb, f"seed {seed} frame {f}")
                touched += sum(1 for p in fa[:-1] if p[2])
            self.assertEqual(la, lb, f"seed {seed}: touching_sides changes")
            self.assertGreater(len(la), 50, "fixture: contacts must begin and end")
        self.assertGreater(touched, 2000, "fixture: bodies must touch")

    def test_invariants_after_every_step(self):
        self.run_scene(7, True, frames=120, check=True)


class TestCanary(unittest.TestCase):
    def test_bounds_kept_past_a_move_are_caught(self):
        """Stored bounds kept whatever the key: a moved body keeps an old box."""
        real = C.CollisionSystem._store_resolved_aabbs

        def keep_all(self_):
            for c in self_._colliders:
                if c._in_resolve and c._resolved_aabb is not None:
                    c._resolved_key = c._proxy_key       # pretend nothing moved
            real(self_)

        case = TestSameFrames("test_invariants_after_every_step")
        with mock.patch.object(C.CollisionSystem, "_store_resolved_aabbs", keep_all):
            with self.assertRaises(AssertionError):
                case.test_invariants_after_every_step()

    def test_a_forgotten_toucher_is_caught(self):
        """The last publish's bodies dropped: one that stops touching keeps its sides."""
        real = C.CollisionSystem._update_touching_state

        def forget(self_, current, id_to_collider):
            self_._touching_live = {}
            return real(self_, current, id_to_collider)

        case = TestSameFrames("test_invariants_after_every_step")
        with mock.patch.object(C.CollisionSystem, "_update_touching_state", forget):
            with self.assertRaises(AssertionError):
                case.test_invariants_after_every_step()


if __name__ == "__main__":
    unittest.main()
