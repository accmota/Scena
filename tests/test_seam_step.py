"""Seam lips: a walker steps over a tiny rise between two tiles.

Rule under test (Collision Design.md, "Seam lips (step-up)"): a body that
stood on a floor last frame (or met one earlier this frame) and walks into
the side face of a still partner whose top is at most ``_SEAM_STEP`` above
its feet steps onto that partner. It neither stops (solid pair) nor passes
into it (``only=`` pair). Everything else is unchanged: a taller lip is a wall
(solid) or a walk-through (one-way), an airborne body gets no ledge grab, a
ceiling or a moving partner refuses the step, a steep face is not a floor.

Bug class guarded (SU in Testing Design): tiles placed a hair apart (a rotated
row, integer coordinates, a scaled hull) leave a lip larger than the resting
skin ``_RESOLVE_SLOP``. The walker's leading corner then meets the next tile's
side face first, and a horizontal normal stopped it dead or (one-way) started
a pass and dropped it into the tile, with a frame-rate dependent threshold.

    python -m unittest tests.test_seam_step -v
"""
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.collision import (  # noqa: E402
    STATIC,
    _RESOLVE_SLOP,
    _SEAM_STEP,
    get_collision_system,
    reset_collision_system,
    resolve,
)
from scena.shapes import Polygon, Rect  # noqa: E402
from scena.scenamath import Vec2  # noqa: E402

coll = sys.modules["scena.collision"]   # the name ``scena.collision`` is the query facade

GRAVITY = 900.0
HERO_W = 38.0
HERO_H = 70.0
TILE_W = 80.0
TILE_H = 40.0
RUN = 250.0

PACINGS = {
    "30 Hz": [1 / 30],
    "60 Hz": [1 / 60],
    "144 Hz": [1 / 144],
    "240 Hz": [1 / 240],
    "5 / 28 ms": [0.005, 0.028],
}
LIPS = (0.1, 0.34, 1.0, 1.9)


def only_bottom(c):
    return c.side == "bottom"


MODES = {
    "solid": None,
    "only='bottom'": "bottom",
    "only=function": only_bottom,
}

# The ninja_perigos platform as the collider saw it (Tiles 13/14/15.png,
# 80 x 58.125, angle 15): tile 2 starts 0.34 DU above tile 1's top at the seam.
NINJA_HULLS = [
    [(978.34, 246.86), (980.1, 249.95), (1054.96, 270.0), (1070.0, 213.86),
     (1050.68, 208.68), (1031.81, 211.48), (995.84, 220.15), (982.26, 232.21)],
    [(1052.67, 269.45), (1129.95, 290.15), (1144.99, 234.01), (1067.71, 213.31)],
    [(1129.75, 290.49), (1204.61, 310.55), (1207.68, 308.75), (1211.6, 294.11),
     (1211.15, 286.14), (1205.87, 276.87), (1164.11, 239.52), (1144.79, 234.35)],
]


class SeamCase(unittest.TestCase):
    _origin = 0

    def setUp(self):
        reset_collision_system()
        self._owned = []
        SeamCase._origin += 5000
        self.ox = float(SeamCase._origin)
        self.oy = float(SeamCase._origin)

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

    def tile(self, x, top, width=TILE_W, height=TILE_H, angle=0.0, group="chao"):
        t = self.track(Rect(
            center=(self.ox + x, self.oy + top - height / 2.0),
            width=width, height=height, angle=angle, group=group,
        ))
        t.mass = STATIC
        return t

    def poly(self, pts, group="chao"):
        p = self.track(Polygon(
            points=[(self.ox + x, self.oy + y) for x, y in pts], group=group,
        ))
        p.mass = STATIC
        return p

    def hero(self, x, bottom):
        h = self.track(Rect(
            center=(self.ox + x, self.oy + bottom + HERO_H / 2.0),
            width=HERO_W, height=HERO_H, group="heroi",
        ))
        h.mass = 1.0
        h.vel = Vec2(0.0, 0.0)
        return h

    def row(self, lip, group="chao"):
        """Three flat tiles, tops at 0, 0 and ``lip``; seams at x = 40 and 120."""
        return [self.tile(0.0, 0.0, group=group), self.tile(80.0, 0.0, group=group),
                self.tile(160.0, lip, group=group)]

    def x(self, h):
        return float(h.center.x) - self.ox

    def bottom(self, h):
        return float(h.center.y) - HERO_H / 2.0 - self.oy

    def frame(self, h, dt, vx=None):
        h.vel.y -= GRAVITY * dt
        if vx is not None:
            h.vel.x = vx
        h.move_by(float(h.vel.x) * dt, float(h.vel.y) * dt)
        get_collision_system().step()

    def land(self, h, pacing, frames=40):
        for i in range(frames):
            self.frame(h, pacing[i % len(pacing)], vx=0.0)
        self.assertIn("bottom", h.touching_sides, "hero never landed")

    def passing(self, h, other):
        sys_ = get_collision_system()
        for bid, inner in sys_._passing.items():
            for cb in inner.values():
                if cb._identity is other:
                    return True
        return False


class TestFlatLips(SeamCase):
    """A lip below ``_SEAM_STEP`` is crossed at every pacing, solid or one-way."""

    def walk(self, lip, only, pacing):
        tiles = self.row(lip)
        h = self.hero(x=-10.0, bottom=0.5)
        resolve("heroi", "chao", bounce=0.0, only=only)
        self.land(h, pacing)
        x0 = self.x(h)
        travelled_t = 0.0
        i = 0
        on_lip = 0
        while self.x(h) < 160.0:
            dt = pacing[i % len(pacing)]
            i += 1
            self.frame(h, dt, vx=RUN)
            travelled_t += dt
            self.assertIn("bottom", h.touching_sides,
                          f"lost the floor at x={self.x(h):.2f}")
            self.assertFalse(self.passing(h, tiles[2]), "started a pass at the seam")
            self.assertGreater(self.bottom(h), -1.0, "fell into the row")
            if self.x(h) - HERO_W / 2.0 > 121.0:
                on_lip += 1
                self.assertAlmostEqual(self.bottom(h), lip, delta=_RESOLVE_SLOP + 0.05)
            self.assertLess(i, 2000, "walker stopped at the seam")
        self.assertGreater(on_lip, 0)
        self.assertAlmostEqual(self.x(h) - x0, RUN * travelled_t, delta=0.5,
                               msg="snagged at the seam")
        self.assertEqual([c.other for c in h.touching_contacts], [tiles[2]])

    def test_lips_are_crossed(self):
        for mode, only in MODES.items():
            for lip in LIPS:
                for name, pacing in PACINGS.items():
                    with self.subTest(mode=mode, lip=lip, pacing=name):
                        self.tearDown()
                        self.setUp()
                        self.walk(lip, only, pacing)

    def test_step_down_is_unchanged(self):
        """Walking left off the lip: a drop, held by floor snap as before."""
        for mode, only in MODES.items():
            with self.subTest(mode=mode):
                self.tearDown()
                self.setUp()
                self.row(1.0)
                h = self.hero(x=170.0, bottom=1.5)
                resolve("heroi", "chao", bounce=0.0, only=only)
                self.land(h, [1 / 60])
                for _ in range(40):         # x 170 -> 3: off the lip, still on the row
                    self.frame(h, 1 / 60, vx=-RUN)
                    self.assertIn("bottom", h.touching_sides)
                self.assertAlmostEqual(self.bottom(h), 0.0, delta=_RESOLVE_SLOP + 0.05)

    def test_switch_off_restores_the_bug(self):
        """``_SEAM_STEP = 0`` (the bench A/B switch) brings the snag back."""
        saved = coll._SEAM_STEP
        coll._SEAM_STEP = 0.0
        try:
            self.row(0.34)
            h = self.hero(x=-10.0, bottom=0.5)
            resolve("heroi", "chao", bounce=0.0)
            self.land(h, [1 / 60])
            for _ in range(120):
                self.frame(h, 1 / 60, vx=RUN)
            self.assertIn("right", h.touching_sides)
            self.assertLess(self.x(h), 120.0 - HERO_W / 2.0 + 0.5)
        finally:
            coll._SEAM_STEP = saved


class TestTallLip(SeamCase):
    """Above ``_SEAM_STEP`` nothing changes: a wall, or a one-way walk-through."""

    LIP = _SEAM_STEP + 0.5

    def test_solid_tall_lip_is_a_wall(self):
        for name, pacing in PACINGS.items():
            with self.subTest(pacing=name):
                self.tearDown()
                self.setUp()
                self.row(self.LIP)
                h = self.hero(x=-10.0, bottom=0.5)
                resolve("heroi", "chao", bounce=0.0)
                self.land(h, pacing)
                for i in range(int(1.0 / min(pacing))):
                    self.frame(h, pacing[i % len(pacing)], vx=RUN)
                self.assertIn("right", h.touching_sides)
                self.assertIn("bottom", h.touching_sides)
                self.assertLess(self.x(h), 120.0 - HERO_W / 2.0 + 0.5)
                self.assertAlmostEqual(self.bottom(h), 0.0, delta=_RESOLVE_SLOP + 0.05)

    def test_one_way_tall_lip_is_walked_through(self):
        tiles = self.row(self.LIP)
        h = self.hero(x=-10.0, bottom=0.5)
        resolve("heroi", "chao", bounce=0.0, only="bottom")
        self.land(h, [1 / 60])
        stood_on_lip = False
        for _ in range(60):
            self.frame(h, 1 / 60, vx=RUN)
            for c in h.touching_contacts:
                if c.other is tiles[2]:
                    stood_on_lip = True
        self.assertGreater(self.x(h), 120.0 + HERO_W / 2.0)
        self.assertFalse(stood_on_lip, "a lip taller than the step was climbed")


class TestRotatedRows(SeamCase):
    def test_ninja_platform(self):
        """The reported level: walk uphill over the 0.34 lip, then back down."""
        for mode, only in MODES.items():
            for name, pacing in PACINGS.items():
                with self.subTest(mode=mode, pacing=name):
                    self.tearDown()
                    self.setUp()
                    tiles = [self.poly(p) for p in NINJA_HULLS]
                    h = self.hero(x=1000.0, bottom=270.0)
                    resolve("heroi", "chao", bounce=0.0, only=only)
                    self.land(h, pacing)
                    i = 0
                    while self.x(h) < 1185.0:
                        self.frame(h, pacing[i % len(pacing)], vx=RUN)
                        i += 1
                        self.assertIn("bottom", h.touching_sides,
                                      f"lost the floor at x={self.x(h):.2f}")
                        self.assertFalse(self.passing(h, tiles[2]))
                        self.assertLess(i, 2000, "walker stopped at the seam")
                    self.assertEqual([c.other for c in h.touching_contacts], [tiles[2]])
                    # Turn around from rest: walking uphill leaves the slope's
                    # rise in vel.y, and reversing with it launches (not a seam).
                    h.vel = Vec2(0.0, 0.0)
                    while self.x(h) > 1010.0:
                        self.frame(h, pacing[i % len(pacing)], vx=-RUN)
                        i += 1
                        self.assertIn("bottom", h.touching_sides,
                                      f"lost the floor at x={self.x(h):.2f} (downhill)")
                        self.assertLess(i, 4000, "walker stopped going downhill")

    def test_random_rotated_rows(self):
        """Rows at ±15° / 30° with random lips: never stuck, never through."""
        rng = random.Random(20261011)
        for angle in (-30.0, -15.0, 15.0, 30.0):
            for trial in range(4):
                # Offsets across the row's line. The step is vertical: a seam
                # offset ``d`` across a row at ``angle`` rises d / cos(angle),
                # so each seam stays inside ±(_SEAM_STEP - 0.1) of height.
                most = (_SEAM_STEP - 0.1) * math.cos(math.radians(angle))
                lips, off = [], 0.0
                for _ in range(3):
                    off += rng.uniform(-most, most)
                    lips.append(off)
                only = rng.choice(list(MODES.values()))
                with self.subTest(angle=angle, lips=[round(v, 3) for v in lips],
                                  only=getattr(only, "__name__", only)):
                    self.tearDown()
                    self.setUp()
                    a = math.radians(angle)
                    ux, uy = math.cos(a), math.sin(a)       # along the row
                    nx, ny = -math.sin(a), math.cos(a)      # the row's up
                    tiles = []
                    for k in range(4):
                        off = 0.0 if k == 0 else lips[k - 1]
                        cx = TILE_W * k * ux + (off - TILE_H / 2.0) * nx
                        cy = TILE_W * k * uy + (off - TILE_H / 2.0) * ny
                        t = self.track(Rect(
                            center=(self.ox + cx, self.oy + cy), width=TILE_W,
                            height=TILE_H, angle=angle, group="chao",
                        ))
                        t.mass = STATIC
                        tiles.append(t)
                    h = self.hero(x=0.0, bottom=TILE_W)
                    resolve("heroi", "chao", bounce=0.0, only=only)
                    self.land(h, [1 / 60], frames=120)
                    end = TILE_W * 3 * ux
                    for direction, goal in ((1.0, end), (-1.0, 0.0)):
                        h.vel = Vec2(0.0, 0.0)   # turn from rest (see test_ninja_platform)
                        i = 0
                        while (self.x(h) - goal) * direction < 0.0:
                            self.frame(h, 1 / 60, vx=direction * RUN)
                            i += 1
                            self.assertIn("bottom", h.touching_sides,
                                          f"lost the floor at x={self.x(h):.2f}")
                            for t in tiles:
                                self.assertFalse(self.passing(h, t), "fell into a tile")
                            self.assertLess(i, 600, f"stuck at x={self.x(h):.2f}")


class TestNoStep(SeamCase):
    """Cases the rule must leave alone."""

    def test_airborne_low_ledge_is_a_wall(self):
        """No ledge grab: feet 0.5 below a slab top, in the air, is a side hit."""
        slab = self.tile(100.0, 0.0, width=120.0)
        h = self.hero(x=100.0 - 60.0 - HERO_W / 2.0 - 6.0, bottom=-0.5)
        resolve("heroi", "chao", bounce=0.0)
        y0 = self.bottom(h)
        for _ in range(30):
            self.frame(h, 1 / 60, vx=RUN)
            self.assertNotIn("bottom", h.touching_sides)
        self.assertLess(self.bottom(h), y0 + 0.01)
        self.assertIsNotNone(slab)

    def test_ceiling_over_the_seam_refuses_the_step(self):
        self.row(1.0)
        # Ceiling 0.5 above the head while standing on the low tiles.
        self.tile(80.0, HERO_H + 0.5 + 40.0, width=400.0, height=40.0)
        h = self.hero(x=-10.0, bottom=0.5)
        resolve("heroi", "chao", bounce=0.0)
        self.land(h, [1 / 60])
        for _ in range(90):
            self.frame(h, 1 / 60, vx=RUN)
        self.assertIn("right", h.touching_sides)
        self.assertLess(self.x(h), 120.0 - HERO_W / 2.0 + 0.5)

    def test_steep_rise_is_not_climbed_at_high_frame_rate(self):
        """A 60° face is a wall even when one frame's run is under the step."""
        self.tile(0.0, 0.0, width=400.0)
        ramp = self.track(Rect(center=(self.ox + 120.0, self.oy + 0.0), width=200.0,
                               height=30.0, angle=60.0, group="chao"))
        ramp.mass = STATIC
        h = self.hero(x=-20.0, bottom=0.5)
        resolve("heroi", "chao", bounce=0.0)
        self.land(h, [1 / 240])
        for _ in range(480):
            self.frame(h, 1 / 240, vx=RUN)
        self.assertLess(self.bottom(h), 3.0, "climbed a 60° face")

    def test_moving_partner_is_not_stepped(self):
        tiles = self.row(1.0)
        h = self.hero(x=-10.0, bottom=0.5)
        resolve("heroi", "chao", bounce=0.0)
        self.land(h, [1 / 60])
        sign = 1.0
        for _ in range(90):
            tiles[2].move_by(0.0, sign * 1e-4)   # a lift that is not still
            sign = -sign
            self.frame(h, 1 / 60, vx=RUN)
        self.assertIn("right", h.touching_sides)
        self.assertLess(self.x(h), 120.0 - HERO_W / 2.0 + 0.5)

    def test_still_crate_is_a_wall(self):
        """A dynamic partner taller than the step stops the walker, as before."""
        self.tile(100.0, 0.0, width=600.0)
        crate = self.track(Rect(center=(self.ox + 60.0, self.oy + 15.5), width=30.0,
                                height=30.0, group="caixa"))
        crate.mass = 1.0
        crate.vel = Vec2(0.0, 0.0)
        h = self.hero(x=0.0, bottom=0.5)
        resolve(["heroi", "caixa"], "chao", bounce=0.0)
        resolve("heroi", "caixa", bounce=0.0)
        self.land(h, [1 / 60])
        for _ in range(60):
            crate.vel.y -= GRAVITY / 60.0
            crate.move_by(0.0, float(crate.vel.y) / 60.0)
            self.frame(h, 1 / 60, vx=RUN)
            self.assertLess(self.bottom(h), 1.0, "stepped onto the crate")
        self.assertIn("right", h.touching_sides)

    def test_floor_below_agrees_across_a_lip(self):
        tiles = self.row(1.0)
        h = self.hero(x=60.0, bottom=0.5)
        resolve("heroi", "chao", bounce=0.0)
        self.land(h, [1 / 60])
        self.assertIs(h.floor_below(dx=100.0), tiles[2])


if __name__ == "__main__":
    unittest.main()
