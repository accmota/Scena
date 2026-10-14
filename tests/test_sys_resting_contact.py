"""Resting and sliding contact must not flicker across real frames.

What a player notices is not a 1-ulp tangency (G2) but a contact that
flickers: a body resting on a floor, or walking over a row of touching tiles,
reporting enter / exit / enter. A body lands on a ``STATIC`` floor under
``resolve(..., bounce=0.0)`` and gravity, then rests or walks across tile seams:

* ``touching_sides`` holds ``"bottom"`` every frame after landing, at any frame
  pacing (60 Hz, 144 Hz, 200 Hz, alternating 5 / 28 ms) and far from the origin;
* walking over touching tiles does not snag on a seam (distance = speed x time);
* one-way tiles (``resolve(..., only="bottom")``) hold the walker at every
  pacing: a rejected seam contact must not start a pass-through;
* ``@collide`` on the resolved hero / tile pair enters each tile once and exits
  it once, and a resting body keeps an open contact, at every pacing (F1 fix:
  a standing resolve pair within ``_CONTACT_SKIN`` is a contact, because
  resolve parks the body ``_RESOLVE_SLOP`` short of the floor).

Accepted limitation (F2 in Testing Design, by design): a curved body walking
over tile seams with uneven frames can enter / exit the *next* tile near the
seam. ``@collide`` reads the pre-resolve pose, which sinks by g·dt² (0.6 DU on
a 28 ms frame, none on a 5 ms one), so the gap to a corner swings across any
fixed skin. Authors read ``touching_contacts`` for "which tile am I on". The
case stays ``expectedFailure`` as a tripwire: an unexpected success means the
behaviour changed and the docs need updating.

    python -m unittest tests.test_sys_resting_contact -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import quiet, system_world  # noqa: E402

from scena import STATIC, Circle, Rect, collide, collide_exit, resolve  # noqa: E402
from scena.scenamath import Vec2  # noqa: E402

GRAVITY = 900.0
TILE = 16.0
LANDED = 20            # frames allowed for the drop (1 DU) and the first settle

PACINGS = {
    "60 Hz": [1 / 60],
    "144 Hz": [1 / 144],
    "200 Hz": [0.005],
    "5 / 28 ms": [0.005, 0.028],
}
OFFSETS = (0.0, 65_536.0)
KINDS = ("rect", "circle")


def run(kind, *, pacing, offset=0.0, tiles=1, vx=0.0, frames=150, only=None,
        lowest=None):
    """Drop a hero onto a row of touching tiles, then rest or walk.

    Returns per-frame samples ``(open tile contacts, "bottom" in touching_sides)``,
    the ``@collide`` events as ``(frame, "enter" | "exit", tile index)`` (teardown
    exits excluded), and the hero's x travel. ``only=`` goes to ``resolve``
    (one-way tiles). ``lowest``, a list, receives the lowest hero centre y
    relative to its resting height after landing (a fall-through reads large).
    """
    events, samples = [], []
    with system_world(draw=False) as w:
        with quiet():
            row = [w.track(Rect(center=(offset + TILE * i, offset), width=TILE,
                                height=TILE, group="tile")) for i in range(tiles)]
            for t in row:
                t.mass = STATIC
            top = offset + TILE / 2
            if kind == "rect":
                hero = Rect(center=(offset, top + 10 + 1), width=12, height=20, group="hero")
            else:
                hero = Circle(center=(offset, top + 8 + 1), radius=8, group="hero")
            hero = w.track(hero)
            hero.mass = 1.0
            hero.vel = Vec2(0.0, 0.0)
        resolve("hero", "tile", bounce=0.0, only=only)
        rest_y = top + (10 if kind == "rect" else 8)
        low = [0.0]
        open_tiles = set()
        frame = [0]

        @collide("hero", "tile")
        def _enter(a, b, info=None):
            open_tiles.add(row.index(b))
            events.append((frame[0], "enter", row.index(b)))

        @collide_exit("hero", "tile")
        def _exit(a, b, info=None):
            open_tiles.discard(row.index(b))
            events.append((frame[0], "exit", row.index(b)))

        x0 = float(hero.center.x)
        for k in range(frames):
            frame[0] = k
            dt = pacing[k % len(pacing)]
            hero.vel.x = vx
            hero.vel.y -= GRAVITY * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            w.step(1, dt=dt)
            samples.append((len(open_tiles), "bottom" in hero.touching_sides))
            if k >= LANDED:
                low[0] = min(low[0], float(hero.center.y) - rest_y)
        if lowest is not None:
            lowest.append(low[0])
        travel = float(hero.center.x) - x0
        seen = list(events)          # before teardown adds its exits
    return samples, seen, travel


def _elapsed(pacing, frames):
    return sum(pacing[k % len(pacing)] for k in range(frames))


class TestTouchingSidesDoNotFlicker(unittest.TestCase):
    """The grounded read (``touching_sides``) is steady at every pacing."""

    def test_resting_body_stays_grounded(self):
        for kind in KINDS:
            for name, pacing in PACINGS.items():
                for offset in OFFSETS:
                    with self.subTest(kind=kind, pacing=name, offset=offset):
                        samples, _, _ = run(kind, pacing=pacing, offset=offset)
                        airborne = [k for k, (_, ground) in enumerate(samples)
                                    if k >= LANDED and not ground]
                        self.assertEqual(airborne, [], "resting body lost 'bottom'")

    def test_walking_across_tile_seams_stays_grounded_and_does_not_snag(self):
        vx, frames = 60.0, 150
        for kind in KINDS:
            for name, pacing in PACINGS.items():
                for offset in OFFSETS:
                    with self.subTest(kind=kind, pacing=name, offset=offset):
                        samples, _, travel = run(kind, pacing=pacing, offset=offset,
                                                 tiles=12, vx=vx, frames=frames)
                        airborne = [k for k, (_, ground) in enumerate(samples)
                                    if k >= LANDED and not ground]
                        self.assertEqual(airborne, [], "lost 'bottom' on a seam")
                        self.assertAlmostEqual(travel, vx * _elapsed(pacing, frames),
                                               delta=0.5, msg="snagged on a tile seam")


class TestOneWayTilesHold(unittest.TestCase):
    """``resolve(..., only="bottom")`` tiles: the walker never drops through a
    seam. A rejected side contact at a seam would start a pass on the next
    tile, and the walker would fall when it left the current one."""

    def test_walking_across_one_way_tiles(self):
        vx, frames = 60.0, 150
        for kind in KINDS:
            for name, pacing in PACINGS.items():
                for offset in OFFSETS:
                    with self.subTest(kind=kind, pacing=name, offset=offset):
                        lowest = []
                        samples, _, travel = run(kind, pacing=pacing, offset=offset,
                                                 tiles=12, vx=vx, frames=frames,
                                                 only="bottom", lowest=lowest)
                        airborne = [k for k, (_, ground) in enumerate(samples)
                                    if k >= LANDED and not ground]
                        self.assertEqual(airborne, [], "lost 'bottom' on a one-way seam")
                        self.assertGreater(lowest[0], -1.0, "sank into a one-way tile")
                        self.assertAlmostEqual(travel, vx * _elapsed(pacing, frames),
                                               delta=0.5, msg="snagged on a one-way seam")


def _collide_flicker(test, kind, pacing, offset, *, walk):
    tiles, vx = (12, 60.0) if walk else (1, 0.0)
    samples, events, _ = run(kind, pacing=pacing, offset=offset, tiles=tiles, vx=vx)
    dropped = [k for k, (n, _) in enumerate(samples) if k >= LANDED and n == 0]
    test.assertEqual(dropped, [], "no open @collide contact while standing on a tile")
    per_tile = {}
    for _, what, i in events:
        per_tile.setdefault(i, []).append(what)
    flicker = {i: seq for i, seq in per_tile.items()
               if seq not in (["enter"], ["enter", "exit"])}
    test.assertEqual(flicker, {}, "a tile was entered again (enter / exit flicker)")


class TestCollideDoesNotFlicker(unittest.TestCase):
    """``@collide`` on the resolved hero / tile pair, every kind x pacing x
    offset, resting and walking (F1)."""

    def test_resting(self):
        for kind in KINDS:
            for name, pacing in PACINGS.items():
                for offset in OFFSETS:
                    with self.subTest(kind=kind, pacing=name, offset=offset):
                        _collide_flicker(self, kind, pacing, offset, walk=False)

    def test_walking_across_tile_seams(self):
        for kind in KINDS:
            for name, pacing in PACINGS.items():
                if kind == "circle" and name == "5 / 28 ms":
                    continue        # F2: test_curved_body_on_seams_with_uneven_frames
                for offset in OFFSETS:
                    with self.subTest(kind=kind, pacing=name, offset=offset):
                        _collide_flicker(self, kind, pacing, offset, walk=True)

    def test_skin_is_what_keeps_the_resting_contact(self):
        """Guard for the guard: with no skin, resting at 200 Hz flickers again."""
        from unittest import mock
        with mock.patch("scena.collision._CONTACT_SKIN", 0.0):
            with self.assertRaises(AssertionError):
                _collide_flicker(self, "rect", PACINGS["200 Hz"], 0.0, walk=False)

    # F2 (accepted limitation, tripwire): the pre-resolve pose sinks by g·dt²,
    # so a corner gap swings across the skin frame to frame. If this starts
    # passing, update Collision Design § Resting contact (skin) and F2.
    @unittest.expectedFailure
    def test_curved_body_on_seams_with_uneven_frames(self):
        _collide_flicker(self, "circle", PACINGS["5 / 28 ms"], 0.0, walk=True)


SETTLE = 10            # frames on a still lift before it moves


def ride(kind, *, pacing, lift_v, frames=120, yoyo=False, gravity=GRAVITY):
    """A hero rests on a ``STATIC`` lift that moves by ``move_by`` (down at
    ``lift_v`` DU/s, or up and down when ``yoyo``) once the hero has landed.
    Returns the per-frame samples ``(open @collide contact, "bottom" in
    touching_sides)`` while the lift moves and the ``@collide`` /
    ``@collide_exit`` events."""
    events, samples = [], []
    with system_world(draw=False) as w:
        with quiet():
            lift = w.track(Rect(center=(0.0, 0.0), width=100, height=20, group="lift"))
            lift.mass = STATIC
            if kind == "rect":
                hero = Rect(center=(0.0, 10 + 20 + 0.08), width=30, height=40, group="rider")
            else:
                hero = Circle(center=(0.0, 10 + 12 + 0.08), radius=12, group="rider")
            hero = w.track(hero)
            hero.vel = Vec2(0.0, 0.0)
        resolve("rider", "lift", bounce=0.0)
        open_ = [False]
        frame = [0]

        @collide("rider", "lift")
        def _enter(a, b, info=None):
            open_[0] = True
            events.append((frame[0], "enter"))

        @collide_exit("rider", "lift")
        def _exit(a, b, info=None):
            open_[0] = False
            events.append((frame[0], "exit"))

        t = 0.0
        for k in range(frames):
            frame[0] = k
            dt = pacing[k % len(pacing)]
            t += dt
            hero.vel.y -= gravity * dt
            hero.move_by(0.0, hero.vel.y * dt)
            v = lift_v if k >= SETTLE else 0.0      # lands on a still lift first
            if yoyo and (t % 1.0) >= 0.5:
                v = -v
            lift.move_by(0.0, v * dt)
            w.step(1, dt=dt)
            if k >= SETTLE:
                samples.append((open_[0], "bottom" in hero.touching_sides))
        seen = list(events)
    return samples, seen


class TestRiderOnAMovingLift(unittest.TestCase):
    """PB4 (2026-10-14): a rider on a descending ``STATIC`` lift is grounded
    (floor snap) but its pre-resolve gap is the slop plus the lift's drop
    minus its own fall, past the fixed skin: ``touching_sides`` said
    "bottom" while ``@collide`` exited (60 DU/s at 60 Hz; 30 DU/s at 144 Hz;
    a yoyo lift exited at the top and never re-entered on the way down).
    The skin widens by how far an immovable partner moved away this frame."""

    def test_descending_lift_keeps_the_contact(self):
        for kind in KINDS:
            for name, pacing in PACINGS.items():
                for v in (-30.0, -60.0, -100.0, -200.0):
                    with self.subTest(kind=kind, pacing=name, lift_v=v):
                        samples, events = ride(kind, pacing=pacing, lift_v=v)
                        grounded = [k for k, (_, g) in enumerate(samples) if g]
                        self.assertEqual(len(grounded), len(samples), "rider left the lift")
                        lost = [k for k, (o, g) in enumerate(samples) if g and not o]
                        self.assertEqual(lost, [], "grounded, but no open @collide contact")
                        self.assertEqual([e for _, e in events], ["enter"])

    def test_yoyo_lift_keeps_the_contact(self):
        for kind in KINDS:
            for name, pacing in PACINGS.items():
                with self.subTest(kind=kind, pacing=name):
                    samples, events = ride(kind, pacing=pacing, lift_v=60.0,
                                           yoyo=True, frames=240)
                    lost = [k for k, (o, g) in enumerate(samples) if g and not o]
                    self.assertEqual(lost, [])
                    self.assertEqual([e for _, e in events], ["enter"])

    def test_the_carry_is_what_keeps_the_contact(self):
        """Guard for the guard: with no carry opening, 30 DU/s at 144 Hz
        loses the contact again."""
        from unittest import mock
        with mock.patch("scena.collision._carry_opening", lambda a, b: (0.0, 0.0, 0.0)):
            samples, events = ride("rect", pacing=PACINGS["144 Hz"], lift_v=-30.0)
        self.assertTrue(any(g and not o for o, g in samples))

    def test_jumping_off_a_descending_lift_exits(self):
        """The widening counts only the lift's motion: a rider that leaves
        it (here: jumps) exits on that frame."""
        with system_world(draw=False) as w:
            with quiet():
                lift = w.track(Rect(center=(0.0, 0.0), width=100, height=20, group="lift"))
                lift.mass = STATIC
                hero = w.track(Rect(center=(0.0, 30.08), width=30, height=40, group="rider"))
                hero.vel = Vec2(0.0, 0.0)
            resolve("rider", "lift", bounce=0.0)
            log = []

            @collide_exit("rider", "lift")
            def _exit(a, b, info=None):
                log.append(w.frames_run)

            for k in range(20):
                hero.vel.y -= GRAVITY / 60
                hero.move_by(0.0, hero.vel.y / 60)
                lift.move_by(0.0, -1.0 if k >= SETTLE else 0.0)
                w.step(1, dt=1 / 60)
            self.assertEqual(log, [])
            hero.vel.y = 300.0
            hero.move_by(0.0, 5.0)
            lift.move_by(0.0, -1.0)
            w.step(1, dt=1 / 60)
            self.assertEqual(log, [20])


if __name__ == "__main__":
    unittest.main()
