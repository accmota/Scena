"""
The claims of ``examples/guardian.py``, played headless.

The example says: the game opens on the story, SPACE starts it, and R after
the end goes straight to a fresh game (the story is told once); the ship
flies around the ring (one angle that is never wrapped, so the two lights
that chase it never take the long way past 360); it shoots outward, and a
narrow radar pulls a shot onto an enemy almost in front; an Arrow dies in one
shot, a Mandala in three, a Crystal in five; a shot that meets an enemy shot
zaps them both; a shot Mine blows up the enemies around it, other mines in a
chain; a crossing mine passes CROSSING from the center and leaves; a diving
mine costs the ring or the ship MINE_DAMAGE; an enemy shot costs the ship or
the ring one life, and so does an enemy that reaches the ring; with TRIPLE
the lights shoot FAN degrees off the ship's line; pills give triple, rapid
and heavy shots and a Portal shield that stops SHIELD_HITS hits or lasts
DURATION seconds; a destroyed enemy drops at most one pill every PILL_GAP
seconds, and the waves marked ``gifts`` leave those pills, which last
GIFT_DURATION (wave 4 leaves heavy and triple shots for the polygons); a
wave's ``ambush`` mine is right in front of the ring that many seconds after
its first enemy (the swarm of wave 6 has one); a wave's ``pace`` makes its
enemies move that much faster (waves 2 and 5: 1.5); from many sides
the enemies come in clusters; from one side the ring goes to the far side
of the screen (half off it on an "edge" wave) and the portal stays on the
screen; the waves run one after the other to "THE RING IS SAFE", the camera
turns only on the waves marked ``turn``, the embers come once (the wave marked
``party``) and the victory is geometric (``celebrate``: a four-point
Starburst, opening hexagons, lights around the ring), with no embers;
the game plays sound (shots, hits, explosions, the ring's bell, music).

Bug classes guarded: **an example that stops doing what its docstring says**
while it still builds and runs, and **a power-up that never ends** (the
shield Portal must leave when its time or its hits run out).

Run:

    python tests/run_tiers.py focused test_example_guardian
"""
from __future__ import annotations

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402
from scena.act import get_act_manager  # noqa: E402

PATH = "examples/guardian.py"
SECOND = 60


def act():
    return get_act_manager().current


def count(ns, name):
    return len(list(ns["group"][name]))


def tap(run, key):
    run.key_down(key)
    run.step(1)
    run.key_up(key)


def start(run):
    """Past the story: SPACE starts the game."""
    run.step(2)
    tap(run, "SPACE")
    run.step(2)


def quiet(run):
    """The game with no waves: each test places its own enemies."""
    start(run)
    act().waves.cancel()
    return run.ns, act().ship


def still(ns, kind, angle, far):
    """An enemy that stays where it is put (its timers and moves cancelled)."""
    enemy = ns[kind](center=ns["on_ring"](angle, far))
    enemy.cancel_process()
    return enemy


def shots_fired(run, ns, ship, frames=SECOND):
    """Shots made in ``frames`` frames of SPACE, from a ready gun."""
    old = list(ns["group"]["shots"])     # still flying from before
    seen = []                       # the shots themselves: an id() is reused
    ship.reload = 0
    run.key_down("SPACE")
    for _ in range(frames):
        run.step(1)
        for shot in ns["group"]["shots"]:
            if not any(shot is s for s in seen + old):
                seen.append(shot)
    run.key_up("SPACE")
    run.step(SECOND)
    return len(seen)


def on_screen(ns, point):
    """Where a world point is on the screen, from the camera's public reads."""
    canvas = ns["canvas"]
    z, r = canvas.zoom, math.radians(canvas.rotation)
    x, y = point
    dx = (float(x) - canvas.pan_x) * z
    dy = (float(y) - canvas.pan_y) * z
    return (640 + dx * math.cos(r) - dy * math.sin(r),
            400 + dx * math.sin(r) + dy * math.cos(r))


class TestGuardianStory(unittest.TestCase):
    def test_the_game_plays_sound(self):
        with ProgramRun(PATH) as run:
            ns = run.ns
            played = []
            real = ns["play_sound"]
            ns["play_sound"] = lambda source, **kw: played.append(source) or real(source, **kw)
            run.step(SECOND)        # (the story's music started before the patch)
            tap(run, "SPACE")
            run.step(3)
            ship = act().ship
            act().waves.cancel()
            ship.reload = 0
            tap(run, "SPACE")
            ns["shoot_down"](still(ns, "Arrow", 0, 500))
            ns["hurt_ring"]()
            ship.hurt()
            for sound in ("music/battle_in_the_winter.ogg", "audio/laser7.wav",
                          "audio/explosion07.wav", "audio/impactBell_heavy_000.ogg",
                          "audio/impactPunch_heavy_001.ogg"):
                self.assertIn(sound, played)

    def test_the_story_is_typed_and_space_starts_the_game(self):
        with ProgramRun(PATH) as run:
            ns = run.ns
            run.step(SECOND)
            self.assertEqual(type(act()).__name__, "Intro")
            self.assertTrue(ns["STORY"].startswith(act().story.text))
            self.assertLess(len(act().story.text), len(ns["STORY"]))
            self.assertFalse(act().prompt.visible)
            run.step(int(len(ns["STORY"]) / ns["LETTERS"] * SECOND))
            self.assertEqual(act().story.text, ns["STORY"])
            seen = []
            for _ in range(2 * SECOND):
                run.step(1)
                seen.append(act().prompt.visible)
            self.assertTrue(any(seen) and not all(seen), "the prompt does not blink")
            tap(run, "SPACE")
            run.step(1)
            self.assertEqual(type(act()).__name__, "Game")


class TestGuardianShip(unittest.TestCase):
    def test_the_lights_follow_the_ship_past_360_without_a_jump(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            run.key_down("LEFT")
            biggest = 0.0
            before = (ship.light_a, ship.light_b)
            for _ in range(4 * SECOND):
                run.step(1)
                now = (ship.light_a, ship.light_b)
                biggest = max(biggest, *(abs(a - b) for a, b in zip(now, before)))
                before = now
            run.key_up("LEFT")
            self.assertGreater(ship.bearing, 360 + 90, "vacuous: the ship did not pass 360")
            self.assertLess(biggest, 5, "a light jumped")
            x, y = float(ship.center.x), float(ship.center.y)
            cx, cy = float(ns["CENTER"].x), float(ns["CENTER"].y)
            self.assertAlmostEqual(math.dist((x, y), (cx, cy)), ns["ORBIT"], delta=0.5)
            run.step(2 * SECOND)
            for light, side in ((ship.light_a, 1), (ship.light_b, -1)):
                self.assertAlmostEqual(light, ship.bearing + side * ns["SPREAD"], delta=0.5)

    def test_shots_need_one_three_and_five_hits(self):
        for kind, hits in (("Arrow", 1), ("Mandala", 3), ("Crystal", 5)):
            with self.subTest(kind=kind), ProgramRun(PATH) as run:
                ns, ship = quiet(run)
                ns["PILL_CHANCE"] = 0
                enemy = still(ns, kind, 90, 480)
                self.assertEqual(enemy.life, hits)
                run.key_down("SPACE")
                for _ in range(3 * SECOND):
                    run.step(1)
                    if count(ns, "enemies") == 0:
                        break
                run.key_up("SPACE")
                self.assertEqual(count(ns, "enemies"), 0, f"{kind} survived")
                self.assertEqual(ns["st"].score, enemy.worth)

    def test_the_radar_pulls_a_shot_onto_an_enemy_almost_in_front(self):
        hit = {}
        for aim in (0.0, None):
            with ProgramRun(PATH) as run:
                ns, ship = quiet(run)
                if aim is not None:
                    ns["AIM"] = aim
                enemy = still(ns, "Crystal", 92, 600)     # 2 degrees off the shot
                enemy.radius = 10
                run.key_down("SPACE")
                run.step(12)
                run.key_up("SPACE")
                run.step(SECOND)
                hit[aim] = enemy.life < 5
        self.assertFalse(hit[0.0], "vacuous: the straight shot hits anyway")
        self.assertTrue(hit[None], "the radar did not pull the shot")

    def test_a_shot_that_meets_an_enemy_shot_zaps_both(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            st = ns["st"]
            bullet = ns["Bullet"](center=ns["on_ring"](90, 700), angle=-90)
            ship.reload = 0
            run.key_down("SPACE")
            run.step(1)
            run.key_up("SPACE")
            run.step(2 * SECOND)
            self.assertFalse(bullet.active)
            self.assertEqual(count(ns, "shots"), 0, "the shot flew on")
            self.assertEqual((st.ship_life, st.ring_life),
                             (ns["SHIP_LIFE"], ns["RING_LIFE"]))

    def test_a_mine_takes_its_neighbours_and_the_next_mine(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            ns["PILL_CHANCE"] = 0
            still(ns, "Mine", 90, 330)
            still(ns, "Mine", 104, 360)          # inside the first blast
            still(ns, "Arrow", 80, 350)
            still(ns, "Crystal", 100, 450)       # in the blast, out of the aim cone
            far = still(ns, "Mandala", 150, 330)
            run.key_down("SPACE")
            run.step(30)
            run.key_up("SPACE")
            run.step(30)
            self.assertEqual(list(ns["group"]["enemies"]), [far])
            self.assertEqual(count(ns, "mines"), 0)
            self.assertEqual(ns["st"].score, 20 + 20 + 10 + 50)

    def test_a_crossing_mine_passes_in_front_of_the_ring_and_leaves(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            ns["cross_mine"](90)
            mine = list(ns["group"]["mines"])[0]
            cx, cy = float(ns["CENTER"].x), float(ns["CENTER"].y)
            nearest = 1e9
            for _ in range(30 * SECOND):
                run.step(1)
                if not mine.active:
                    break
                nearest = min(nearest, math.dist((float(mine.center.x),
                                                  float(mine.center.y)), (cx, cy)))
            self.assertFalse(mine.active, "the mine never left")
            self.assertAlmostEqual(nearest, ns["CROSSING"], delta=5)
            self.assertEqual(ns["st"].ring_life, ns["RING_LIFE"])


class TestGuardianLives(unittest.TestCase):
    def test_enemy_shots_and_invaders_cost_one_life(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            st = ns["st"]
            ns["Bullet"](center=ns["on_ring"](90, 420), angle=-90)
            run.step(2 * SECOND)
            self.assertEqual(st.ship_life, ns["SHIP_LIFE"] - 1)
            ns["Bullet"](center=ns["on_ring"](270, 420), angle=90)   # at the ring
            run.step(3 * SECOND)
            self.assertEqual(count(ns, "bullets"), 0)
            self.assertEqual(st.ring_life, ns["RING_LIFE"] - 1)
            still(ns, "Arrow", 270, 420)         # no shot of its own
            run.step(4 * SECOND)
            self.assertEqual(st.ring_life, ns["RING_LIFE"] - 2)

    def test_a_diving_mine_hits_hard(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            st = ns["st"]
            ns["DivingMine"](center=ns["on_ring"](270, 400))     # the ship is at 90
            run.step(10 * SECOND)
            self.assertEqual(st.ring_life, ns["RING_LIFE"] - ns["MINE_DAMAGE"])
            self.assertEqual(st.ship_life, ns["SHIP_LIFE"])
            ns["DivingMine"](center=ns["on_ring"](90, 400))
            run.step(10 * SECOND)
            self.assertEqual(st.ship_life, ns["SHIP_LIFE"] - ns["MINE_DAMAGE"])
            self.assertEqual(st.ring_life, ns["RING_LIFE"] - ns["MINE_DAMAGE"])
            self.assertEqual(count(ns, "mines"), 0)

    def test_losing_ends_the_game_and_r_starts_a_fresh_one_without_the_story(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            st = ns["st"]
            ship.hurt(ns["SHIP_LIFE"])
            run.step(2 * SECOND)
            self.assertTrue(act().over)
            self.assertFalse(ship.active, "the ship was not destroyed")
            tap(run, "R")
            run.step(5)
            self.assertEqual(type(act()).__name__, "Game")
            self.assertFalse(act().over)
            self.assertEqual((st.ship_life, st.ring_life, st.score),
                             (ns["SHIP_LIFE"], ns["RING_LIFE"], 0))


class TestGuardianPowers(unittest.TestCase):
    def test_rapid_and_triple_shoot_more(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            normal = shots_fired(run, ns, ship)
            ship.gain("rapid")
            fast = shots_fired(run, ns, ship)
            ship.powers["rapid"] = 0
            ship.gain("triple")
            triple = shots_fired(run, ns, ship)
            self.assertGreaterEqual(fast, 2 * normal - 1)
            self.assertEqual(triple, 3 * normal)
            ship.reload = 0
            tap(run, "SPACE")
            run.step(1)
            new = sorted(round(s.angle - ship.bearing, 3) for s in ns["group"]["shots"]
                         if abs(s.angle - ship.bearing) < 20 and s.center.y > 400)
            self.assertEqual(new[:1] + new[-1:], [-ns["FAN"], ns["FAN"]])

    def test_heavy_shots_go_through(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            ship.gain("heavy")
            still(ns, "Arrow", 90, 380)
            still(ns, "Arrow", 90, 460)
            run.key_down("SPACE")
            run.step(4)
            run.key_up("SPACE")
            run.step(SECOND)
            self.assertEqual(count(ns, "enemies"), 0, "one shot did not pass through both")

    def test_a_pill_gives_the_shield_and_the_shield_ends_in_time(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            ns["drop_pill"](ns["on_ring"](90, 260), "shield")
            run.step(4 * SECOND)
            self.assertIsNotNone(ship.shield, "the pill was not picked up")
            self.assertIn("SHIELD", act().panel.text)
            run.step(int(ns["DURATION"] * SECOND))
            self.assertIsNone(ship.shield, "the shield never ended")
            self.assertEqual(count(ns, "shield"), 0)
            self.assertEqual(act().panel.text, "")

    def test_the_shield_stops_its_hits_then_breaks(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            st = ns["st"]
            ship.gain("shield")
            hits = ns["SHIELD_HITS"]
            for k in range(hits):
                ns["Bullet"](center=ns["on_ring"](200 + 30 * k, 430), angle=20 + 30 * k)
                run.step(SECOND)
            run.step(2 * SECOND)
            self.assertEqual((st.ship_life, st.ring_life), (ns["SHIP_LIFE"], ns["RING_LIFE"]))
            self.assertIsNone(ship.shield, "the shield outlived its hits")
            self.assertEqual(ship.powers["shield"], 0)
            ns["Bullet"](center=ns["on_ring"](250, 430), angle=70)
            run.step(3 * SECOND)
            self.assertEqual(st.ring_life, ns["RING_LIFE"] - 1, "no shield, no stop")

    def test_a_diving_mine_breaks_the_shield_at_once(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            st = ns["st"]
            ship.gain("shield")
            ns["DivingMine"](center=ns["on_ring"](270, 400))
            run.step(8 * SECOND)
            self.assertIsNone(ship.shield)
            self.assertEqual(st.ring_life, ns["RING_LIFE"])

    def test_a_gift_lasts_a_whole_wave(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            self.assertGreater(ns["GIFT_DURATION"], ns["DURATION"])
            ns["leave_gifts"](["heavy"], ship.bearing)
            run.step(int(5 * SECOND))
            self.assertGreater(ship.powers["heavy"], 0, "the gift was not picked up")
            run.step(int((ns["DURATION"] + 1) * SECOND))
            self.assertGreater(ship.powers["heavy"], 0, "a gift lasts only DURATION")
            run.step(int((ns["GIFT_DURATION"] - ns["DURATION"]) * SECOND))
            self.assertEqual(ship.powers["heavy"], 0)

    def test_at_most_one_random_pill_every_pill_gap(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            ns["PILL_CHANCE"] = 1
            dropped = []
            ns["drop_pill"] = lambda place, power=None, lasting=0: dropped.append(power)
            for k in range(8):
                ns["shoot_down"](still(ns, "Arrow", 30 * k, 500))
            self.assertEqual(len(dropped), 1)
            run.step(int((ns["PILL_GAP"] - 2) * SECOND))
            ns["shoot_down"](still(ns, "Arrow", 0, 500))
            self.assertEqual(len(dropped), 1, "a pill before PILL_GAP")
            run.step(3 * SECOND)
            ns["shoot_down"](still(ns, "Arrow", 0, 500))
            self.assertEqual(len(dropped), 2)


class TestGuardianWaves(unittest.TestCase):
    def test_a_timed_mine_is_in_front_of_the_ring_on_time(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            ns["cross_mine"](330, 9)
            mine = list(ns["group"]["mines"])[0]
            front = ns["on_ring"](330, ns["CROSSING"])
            run.step(9 * SECOND)
            self.assertLess(math.dist((float(mine.center.x), float(mine.center.y)),
                                      (float(front.x), float(front.y))), 10)
            ambush = [wave for wave in ns["WAVES"] if wave.get("ambush")]
            self.assertEqual([wave["name"] for wave in ambush], ["Swarm"])

    def test_the_swarm_meets_its_ambush_mine(self):
        """Wave 6 alone: when its mine is in front of the ring, the swarm is
        around it (a shot there takes a good part of the wave)."""
        with ProgramRun(PATH) as run:
            ns = run.ns
            ns["WAVES"][:] = [ns["WAVES"][5]]
            ns["Ship"].hurt = lambda self, damage=1: None
            start(run)
            wave = ns["WAVES"][0]
            run.step(int((1.5 + 2 + wave["ambush"]) * SECOND))
            front = ns["on_ring"](wave["side"], ns["CROSSING"])
            mine = min(ns["group"]["mines"], key=lambda m: math.dist(
                (float(m.center.x), float(m.center.y)), (float(front.x), float(front.y))))
            self.assertLess(math.dist((float(mine.center.x), float(mine.center.y)),
                                      (float(front.x), float(front.y))), 40)
            near = run.ns["collision"].query_circle(mine.center, radius=ns["BLAST"],
                                                    group="enemies")
            self.assertGreaterEqual(len(near), 15, "the swarm is not there yet")

    def test_a_paced_wave_moves_its_enemies_faster(self):
        speeds = {}
        for pace in (1, 1.5):
            with ProgramRun(PATH) as run:
                ns, ship = quiet(run)
                ns["st"].pace = pace
                arrow = ns["Arrow"](center=ns["on_ring"](90, 600))
                crystal = ns["Crystal"](center=ns["on_ring"](270, 600))
                a0 = (float(arrow.center.x), float(arrow.center.y))
                c0 = (float(crystal.center.x), float(crystal.center.y))
                run.step(SECOND)
                speeds[pace] = (
                    math.dist(a0, (float(arrow.center.x), float(arrow.center.y))),
                    math.dist(c0, (float(crystal.center.x), float(crystal.center.y))))
        for slow, fast in zip(speeds[1], speeds[1.5]):
            self.assertGreater(slow, 0, "vacuous: nothing moved")
            self.assertAlmostEqual(fast / slow, 1.5, delta=0.05)
        with ProgramRun(PATH) as run:
            ns = run.ns
            paced = {wave["name"]: wave.get("pace") for wave in ns["WAVES"] if wave.get("pace")}
            self.assertEqual(paced, {"Mandalas": 1.5, "Polygons": 1.5})

    def test_many_sides_come_in_clusters(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            last = 30.0
            for k in range(20):
                side = ns["next_side"](None, k, last)
                self.assertGreaterEqual((side - last) % 360, 100)
                self.assertLessEqual((side - last) % 360, 260)
                last = side
            self.assertEqual([ns["next_side"]([45, 165], k, 0) for k in range(3)],
                             [45, 165, 45])

    def test_from_one_side_the_ring_leaves_the_room_for_the_fight(self):
        with ProgramRun(PATH) as run:
            ns, ship = quiet(run)
            canvas = ns["canvas"]
            game = act()
            edge_waves = 0
            for wave in ns["WAVES"]:
                side = wave["side"]
                if wave.get("turn"):
                    game.turn = 90 - side
                    canvas.rotate_to(game.turn)
                if side is None or isinstance(side, list):
                    continue
                gate = game.frame(wave)
                run.step(int(2.5 * SECOND))
                with self.subTest(wave=wave["name"]):
                    x, y = on_screen(ns, ns["CENTER"])
                    room = min(x, 1280 - x, y, 800 - y)
                    if wave.get("ring") == "edge":
                        edge_waves += 1
                        self.assertAlmostEqual(room, 0, delta=2, msg="not on the edge")
                    else:
                        reach = (ns["ORBIT"] + 28) * canvas.zoom
                        self.assertGreaterEqual(room, reach, "the ship leaves the screen")
                        self.assertGreater(math.dist((x, y), (640, 400)), 150,
                                           "the ring stayed in the middle")
                    px, py = on_screen(ns, ns["on_ring"](side, gate))
                    self.assertTrue(0 <= px <= 1280 and 0 <= py <= 800,
                                    "the portal is off the screen")
                    self.assertGreater(gate, 400)
            self.assertEqual(edge_waves, 1)

    def test_the_waves_run_to_the_end(self):
        """A pilot that aims at the nearest enemy, on an unhurt ship and ring."""
        with ProgramRun(PATH) as run:
            ns = run.ns
            ns["Ship"].hurt = lambda self, damage=1: None
            ns["hurt_ring"] = lambda damage=1: None
            embers = []
            real_embers = ns["Embers"]
            ns["Embers"] = lambda *a, **k: embers.append(1) or real_embers(*a, **k)
            stars = []
            real_star = ns["Starburst"]
            ns["Starburst"] = lambda *a, **k: stars.append(1) or real_star(*a, **k)
            gifts = []
            real_drop = ns["drop_pill"]
            ns["drop_pill"] = lambda place, power=None, lasting=ns["DURATION"]: (
                gifts.append((power, lasting)) if power else None,
                real_drop(place, power, lasting))
            start(run)
            ship = act().ship
            cx, cy = float(ns["CENTER"].x), float(ns["CENTER"].y)
            held = set()

            def hold(key, on):
                if on and key not in held:
                    run.key_down(key)
                    held.add(key)
                elif not on and key in held:
                    run.key_up(key)
                    held.discard(key)

            hold("SPACE", True)
            first = None
            for frame in range(260 * SECOND):
                targets = list(ns["group"]["enemies"]) + list(ns["group"]["mines"])
                turn = 0
                if targets:
                    near = min(targets, key=lambda e: math.dist(
                        (float(e.center.x), float(e.center.y)), (cx, cy)))
                    bearing = math.degrees(math.atan2(float(near.center.y) - cy,
                                                      float(near.center.x) - cx))
                    gap = (bearing - ship.bearing + 180) % 360 - 180
                    turn = 1 if gap > 3 else -1 if gap < -3 else 0
                hold("LEFT", turn > 0)
                hold("RIGHT", turn < 0)
                run.step(1)
                if frame == 4 * SECOND:
                    first = ns["canvas"].rotation
                if act().over:
                    break
            hold("SPACE", False)
            hold("LEFT", False)
            hold("RIGHT", False)
            self.assertTrue(act().over, "the waves never ended")
            self.assertGreater(ns["st"].ring_life, 0, "vacuous: the ring fell")
            turns = [wave["side"] for wave in ns["WAVES"] if wave.get("turn")]
            self.assertEqual(len(turns), 2, "the table should turn the camera twice")
            self.assertAlmostEqual(first, 0, delta=0.01, msg="the camera turned on wave 1")
            self.assertAlmostEqual(ns["canvas"].rotation, 90 - turns[-1], delta=1,
                                   msg="the camera did not turn to the last marked wave")
            self.assertGreater(ns["st"].score, 1000)
            parties = [wave["name"] for wave in ns["WAVES"] if wave.get("party")]
            self.assertEqual(len(embers), len(parties), "embers outside the party waves")
            self.assertEqual(parties, ["Swarm"])
            self.assertEqual(len(stars), 1, "the victory did not celebrate")
            planned = [(p, ns["GIFT_DURATION"]) for wave in ns["WAVES"]
                       for p in wave.get("gifts", [])]
            self.assertEqual(gifts, planned)
            self.assertEqual(ns["WAVES"][2]["gifts"], ["triple", "shield"])
            self.assertEqual(ns["WAVES"][3]["gifts"], ["heavy", "triple"],
                             "no strong weapons before the polygons of wave 5")
            run.step(3 * SECOND)
            self.assertEqual(count(ns, "enemies"), 0)


if __name__ == "__main__":
    unittest.main()
