"""
The claims of ``examples/genesis.py``, played headless.

The example says: the life of a star in six chapters that loop forever
(Nebula, Accretion, Ignition, Supernova, Pulsar, Remnant, then Nebula again);
SPACE goes to the next chapter; a click drops a clump of matter that falls
into the centre and flares there; in chapter V the camera turns with the
beams for a moment (the pulsar stands still, the sky spins); in chapters III
and IV the inner planets go round faster (time ~ distance ** 1.5), and they
keep their places from one chapter to the next. Chapter IV swells the star,
swallows the nearest planet, collapses and blows the star apart.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (act changes with ``fade_out(on_done=)``, ``Track``
``orbit`` / ``move_along(on_done=)``, camera ``rotate_to`` by the shortest
arc, links on ``GlowSpot`` / ``Track`` fields) while it still builds and runs,
**a chapter that warns**: the whole loop is played and must not raise a
single Scena warning (it was checked warning-free in a real window), and
**a loop that leaks**: a death verb (``implode``, ``dissolve_out``) only hides
a shape, so the live objects are counted at the same point of two loops. The
headless run in ``test_scripts_run`` only covers 30 frames of chapter I.

Not covered: drawing (a CPU raster frame of this piece costs 1-4 s headless,
so the visuals and posts are not drawn here).

Run:

    python tests/run_tiers.py focused test_example_genesis
"""
from __future__ import annotations

import math
import os
import sys
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402
from hypothesis_support import registry  # noqa: E402
from scena.act import get_act_manager  # noqa: E402

PATH = "examples/genesis.py"
SECOND = 60
CHAPTERS = ["Cloud", "Disc", "Ignition", "Supernova", "Pulsar", "Remnant"]
# each chapter's own length (its open_chapter call); the fade out adds ~1 s
LENGTHS = {"Cloud": 16, "Disc": 20, "Ignition": 15, "Supernova": 16, "Pulsar": 18, "Remnant": 18}


def act():
    return get_act_manager().current


def act_name() -> str:
    return type(act()).__name__


def tap(run, key):
    run.key_down(key)
    run.step(1)
    run.key_up(key)
    run.step(1)


def next_chapter(run) -> str:
    """SPACE, then wait for the fade and the act change; the new act's name."""
    before = act()
    tap(run, "SPACE")
    for _ in range(2 * SECOND):
        run.step(1)
        if act() is not before:
            return act_name()
    raise AssertionError(f"SPACE did not leave {type(before).__name__}")


def go_to(run, name: str) -> None:
    for _ in range(len(CHAPTERS)):
        if act_name() == name:
            return
        next_chapter(run)
    raise AssertionError(f"never reached {name}")


def live(kind):
    return [o for o in registry().live.values()
            if isinstance(o, kind) and getattr(o, "is_alive", True)]


def angle_gap(a: float, b: float) -> float:
    """b - a in degrees, folded into (-180, 180]."""
    return (b - a + 180) % 360 - 180


class TestGenesisStory(unittest.TestCase):
    def test_six_chapters_loop_without_a_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                st = run.ns["st"]
                seen = [(act_name(), st.title, 0)]
                run.step(1)
                first_loop = len(registry().live)
                for _ in range(115 * SECOND):
                    run.step(1)
                    if act_name() != seen[-1][0]:
                        seen.append((act_name(), st.title, run.frames))
                        if len(seen) > len(CHAPTERS):
                            break
                # the same point of the next loop: nothing piled up (a shape
                # that is only hidden by a death verb stays registered)
                run.step(1)
                second_loop = len(registry().live)
        self.assertEqual([w for w in caught], [], "a chapter raised a Scena warning")
        self.assertLessEqual(second_loop, first_loop, "live objects grew over one loop")
        names = [s[0] for s in seen]
        self.assertEqual(names, CHAPTERS + ["Cloud"], "the story did not loop in order")
        numerals = ["I", "II", "III", "IV", "V", "VI", "I"]
        for (name, title, _), numeral in zip(seen, numerals):
            self.assertEqual(title.split()[0], numeral, (name, title))
        for (name, _, start), (_, _, end) in zip(seen, seen[1:]):
            length = (end - start) / SECOND
            self.assertTrue(LENGTHS[name] <= length <= LENGTHS[name] + 2.5, (name, length))

    def test_space_goes_to_the_next_chapter_once(self):
        with ProgramRun(PATH, seed=1) as run:
            run.step(30)
            # two quick presses: the second one lands during the fade out
            tap(run, "SPACE")
            tap(run, "SPACE")
            for _ in range(2 * SECOND):
                run.step(1)
            self.assertEqual(act_name(), "Disc", "a second SPACE during the fade skipped a chapter")
            self.assertFalse(run.ns["st"].leaving)
            order = [next_chapter(run) for _ in range(5)]
            self.assertEqual(order, CHAPTERS[2:] + ["Cloud"])


class TestGenesisInteractions(unittest.TestCase):
    def test_a_click_drops_matter_into_the_centre(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                c = ns["C"]
                arrived = []
                arrive = ns["arrive"]

                def spy(speck):
                    arrived.append((speck, run.frames, float(speck.center.x), float(speck.center.y)))
                    arrive(speck)

                ns["arrive"] = spy
                run.step(10)
                run.press(200, 650)
                run.step(1)
                run.release()
                pressed = run.frames
                run.step(4 * SECOND)
                self.assertEqual(len(arrived), 5, "the clump is five specks")
                for speck, frame, x, y in arrived:
                    # the orbit curl ends a curl's radius (14) from its path
                    self.assertLess(math.dist((x, y), (c.x, c.y)), 20, "a speck missed the centre")
                    self.assertLess((frame - pressed) / SECOND, 2.2 + 0.18 * 4 + 0.2)
                    self.assertFalse(speck.is_alive, "a speck stays after its flare")
                # specks fall one after the other, each a little later
                frames = [a[1] for a in arrived]
                self.assertEqual(frames, sorted(frames))
                self.assertGreater(frames[-1] - frames[0], 0.5 * SECOND)
        self.assertEqual([w for w in caught], [])


class TestGenesisChapters(unittest.TestCase):
    def test_inner_planets_go_round_faster_and_keep_their_places(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            c, heading = ns["C"], ns["heading"]
            go_to(run, "Ignition")
            run.step(SECOND)
            planets = act().planets
            fars = [p[0] for p in ns["PLANETS"]]
            self.assertEqual([round(math.dist((p.center.x, p.center.y), (c.x, c.y))) for p in planets], fars)
            before = [heading(c, p) for p in planets]
            run.step(SECOND)
            rates = [angle_gap(a, heading(c, p)) for a, p in zip(before, planets)]   # deg/s
            for far, rate in zip(fars, rates):
                self.assertAlmostEqual(360 / abs(rate), (far / 60) ** 1.5 * 2.5, delta=0.3)
            # Kepler: the period grows as distance ** 1.5
            self.assertGreater(abs(rates[0]), abs(rates[1]))
            self.assertGreater(abs(rates[1]), abs(rates[2]))
            # the planets keep their places across the act change: the next
            # chapter's planet is where the old one would be by now
            clock = ns["clock"]
            where = [heading(c, p) for p in planets]
            t = clock.time
            self.assertEqual(next_chapter(run), "Supernova")
            for old, rate, p in zip(where, rates, act().planets):
                self.assertLess(abs(angle_gap(old + rate * (clock.time - t), heading(c, p))), 3, p)

    def test_ignition_lights_the_star(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            go_to(run, "Ignition")
            star = act().star
            self.assertAlmostEqual(star.radius, 10, delta=1)
            run.step(7 * SECOND)
            self.assertAlmostEqual(star.radius, 60, delta=0.5)
            tint = ns["st"].tint
            for got, want in zip(tint.rgb, (1, 0.55, 0.15)):
                self.assertAlmostEqual(got, want, delta=0.02)
            self.assertEqual(star.fill, tint, "the star's fill does not follow st.tint")
            self.assertTrue(all(not t.is_alive for t in act().disc), "the star's wind left the disc")

    def test_supernova_swallows_a_planet_then_blows_apart(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st, c = ns["st"], ns["C"]
            go_to(run, "Supernova")
            chapter = act()
            star = chapter.star
            nearest = chapter.planets[0]
            run.step(5 * SECOND)
            self.assertGreater(star.radius, 120, "the red giant did not swell")
            self.assertNotIn(nearest, chapter.planets, "the nearest planet was not swallowed")
            run.step(int(2.5 * SECOND))
            self.assertFalse(star.is_alive, "the star did not blow apart")
            self.assertGreater(st.shock, 0.5)
            run.step(2 * SECOND)
            self.assertTrue(all(not p.is_alive for p in chapter.planets), "a planet survived the blast")
            # the hot gas rides the blast front (links on GlowSpot.radius)
            gas = [g for g in live(ns["GlowSpot"])
                   if math.dist((g.center.x, g.center.y), (c.x, c.y)) < 1]
            self.assertEqual(len(gas), 2)
            radii = sorted(g.radius for g in gas)
            for size, radius in zip((0.3, 0.45), radii):
                self.assertAlmostEqual(radius, 10 + st.blast * size, delta=1e-6)
            self.assertGreater(st.blast, 500)

    def test_pulsar_camera_turns_with_the_beams_for_a_while(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            canvas, spin = ns["canvas"], ns["spin"]
            go_to(run, "Pulsar")
            chapter = act()
            locked = []
            for _ in range(15 * SECOND):
                run.step(1)
                if chapter.locked:
                    locked.append(run.frames)
                    # the beams stand still on screen: camera = 90 - beam angle
                    self.assertLess(abs(angle_gap(canvas.rotation, 90 - spin())), 1e-6)
                elif not locked:
                    self.assertAlmostEqual(canvas.rotation % 360, 0, delta=1e-6)
            self.assertAlmostEqual(len(locked) / SECOND, 6, delta=0.2)
            # unlock turns back to 0 the short way, within its 2 s
            self.assertLess(abs(angle_gap(0, canvas.rotation)), 1e-6)

    def test_the_remnant_shell_spreads(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st, c = ns["st"], ns["C"]
            go_to(run, "Remnant")
            self.assertEqual(st.exit_style, "iris", "the story does not close on the centre")
            shells = []
            for _ in range(4):
                run.step(3 * SECOND)
                shells.append(st.shell)
                gas = [g for g in live(ns["GlowSpot"])]
                self.assertEqual(len(gas), 8)
                for g in gas:
                    far = math.dist((g.center.x, g.center.y), (c.x, c.y))
                    self.assertAlmostEqual(far, st.shell * 0.95, delta=1e-6)
                    self.assertAlmostEqual(g.radius, 30 + st.shell * 0.3, delta=1e-6)
            self.assertEqual(shells, sorted(shells))
            self.assertGreater(shells[-1], 400)


if __name__ == "__main__":
    unittest.main()
