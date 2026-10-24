"""
The claims of ``examples/tesla.py``, played headless.

The example says: a night in four parts (calm, storm, peak, dawn) that
starts again after a fade; SPACE skips to the next part; power runs along
the cables and a house lights up when it arrives; the city lights one more
window for each step of charge; lightning strikes the tallest thing near
where it falls (a coil, a rod or a house): a coil or a rod feeds the grid, a
house burns out and stays dark for a while; the last strikes linger as
afterimages (a ``History`` of two); a rod dragged next to a house takes its
strikes, and it only slides along the ground; a click makes the nearest coil
discharge there; C toggles the control-room view (``Crt``).

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``History(max_points=, on_leave=)``, links on
``visible`` / ``center`` / ``Track`` ``begin`` / ``end``, ``on_drag_over``,
``Polygon`` points given as lambdas) while it still builds and runs, and
**a part of the night that warns**: the whole night is played and must not
raise a single Scena warning, and **a night that leaks**: a death verb
(``dissolve_out``, ``burn_out``) only hides a shape, so the live objects are
counted at the start of three nights. The headless run in ``test_scripts_run`` only
covers 30 frames of the calm.

Not covered: drawing (a CPU raster frame costs seconds headless).

Run:

    python tests/run_tiers.py focused test_example_tesla
"""
from __future__ import annotations

import contextlib
import math
import os
import sys
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402
from program_support import run_registry  # noqa: E402

PATH = "examples/tesla.py"
SECOND = 60


def tap(run, key):
    run.key_down(key)
    run.step(1)
    run.key_up(key)
    run.step(1)


def spy_bolts(ns):
    """Record every bolt (start, end) the example draws."""
    bolts = []
    bolt = ns["bolt"]

    def spy(start, end, width=3):
        line = bolt(start, end, width)
        bolts.append((tuple(map(float, start)), tuple(map(float, end)), line))
        return line

    ns["bolt"] = spy
    return bolts


def calm_sky(ns):
    """No random strikes: the test strikes by hand."""
    ns["chance"] = lambda odds: False


# Engine finding (2026-10-23, reported, not fixed here): a timed camera verb
# that retargets one still in flight (SPACE skips the storm, so dawn's
# zoom_to(time=6) meets the storm's zoom_to(time=5)) cancels it, as Canvas
# Design says, but warns through the scheduler's fallback ("replaces a
# previous in-flight tween handle", located in scena/canvas.py, with no fix:
# camera verbs take no name=). Only skipping parts by hand reaches it.
CAMERA_RETARGET = "tween/move_along on the same property replaces a previous in-flight tween handle"


@contextlib.contextmanager
def known_warnings_only(test):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
    other = [str(w.message) for w in caught if str(w.message) != CAMERA_RETARGET]
    test.assertEqual(other, [], "a Scena warning")


class TestTeslaNight(unittest.TestCase):
    def test_the_night_plays_and_starts_again_without_a_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                st = ns["st"]
                parts = [st.part]
                lit_in_calm = 0
                storm_top = dawn_top = 0.0
                live = [len(run_registry().live)]     # at the start of each night
                for _ in range(60 * SECOND):
                    run.step(1)
                    if st.part != parts[-1]:
                        parts.append(st.part)
                    if parts == ["calm"]:
                        lit_in_calm = max(lit_in_calm, st.lit)
                    storm_top = max(storm_top, st.storm)
                    dawn_top = max(dawn_top, st.dawn)
                    self.assertTrue(0 <= st.charge <= 1)
                    self.assertTrue(0 <= st.lit <= 3)
                    self.assertLessEqual(len(ns["afterimages"]), 2)
                    if len(parts) == 6:
                        break
                self.assertEqual(parts, ["calm", "storm", "peak", "dawn", "nightfall", "calm"])
                self.assertEqual(lit_in_calm, 3, "power never lit the houses")
                self.assertAlmostEqual(storm_top, 1, delta=1e-6)
                self.assertAlmostEqual(dawn_top, 1, delta=1e-6)
                # back in the calm: the sun went down again and the camera is reset
                self.assertEqual(tuple(ns["sun"].center), (1050, -120))
                self.assertFalse(ns["rays"].enabled)
                self.assertEqual(ns["canvas"].zoom, 1)
                # two more nights: nothing piles up from one night to the next
                # (a death verb only hides a shape; strikes, bolts and sparks
                # must be destroyed)
                live.append(len(run_registry().live))
                for _ in range(2):
                    for _ in range(60 * SECOND):
                        run.step(1)
                        if st.part == "nightfall":
                            break
                    for _ in range(3 * SECOND):
                        run.step(1)
                        if st.part == "calm":
                            break
                    self.assertEqual(st.part, "calm")
                    live.append(len(run_registry().live))
                self.assertLessEqual(max(live[1:]), live[0], f"live objects grew night after night: {live}")
        self.assertEqual([w for w in caught], [], "a part of the night raised a Scena warning")

    def test_space_skips_to_the_next_part(self):
        with known_warnings_only(self), ProgramRun(PATH, seed=1) as run:
            st = run.ns["st"]
            run.step(10)
            order = []
            for _ in range(4):
                tap(run, "SPACE")
                order.append(st.part)
            self.assertEqual(order, ["storm", "peak", "dawn", "nightfall"])
            run.step(2 * SECOND)
            self.assertEqual(st.part, "calm", "the fade did not bring the night back")
            self.assertGreater(st.left, run.ns["PARTS"]["calm"] - 1)

    def test_dawn_lights_the_morning(self):
        with known_warnings_only(self), ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            calm_sky(ns)
            for _ in range(3):
                tap(run, "SPACE")
            self.assertEqual(st.part, "dawn")
            self.assertTrue(ns["rays"].enabled)
            run.step(12 * SECOND)
            self.assertGreater(st.dawn, 0.99)
            self.assertGreater(ns["sun"].center.y, 290, "the sun did not rise")
            # links: the sun's glow rides the sun
            self.assertEqual(tuple(ns["sun_glow"].center), tuple(ns["sun"].center))
            self.assertTrue(all(s.visible for s in ns["shadows"]), "no morning shadows")
            self.assertTrue(ns["morning"].visible)


class TestTeslaPower(unittest.TestCase):
    def test_power_lights_the_houses_and_the_city_follows_the_charge(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            calm_sky(ns)
            houses = ns["houses"]
            self.assertEqual(st.lit, 0)
            run.step(5 * SECOND)
            self.assertEqual(st.lit, 3)
            for h in houses:
                self.assertTrue(h.lit)
                self.assertTrue(all(w.visible for w in h.windows))
            # the city: one more window for each step of charge (a link on
            # visible); ``win`` / ``step`` are the last window and its need
            win, need = ns["win"], ns["step"]
            hud = [t for t in run_registry().live.values()
                   if isinstance(t, ns["Text"]) and str(t.text).startswith("GRID")]
            self.assertEqual(len(hud), 1)
            for charge, level in ((0.9, 18), (0.05, 1), (0.6, 12)):
                st.charge = charge
                run.step(2)
                self.assertEqual(st.level, level)
                self.assertEqual(win.visible, level >= need, charge)
                self.assertTrue(hud[0].text.startswith(f"GRID {level * 5:3d}%"), hud[0].text)

    def test_c_toggles_the_control_room(self):
        with ProgramRun(PATH, seed=1) as run:
            crt = run.ns["crt"]
            self.assertFalse(crt.enabled)
            tap(run, "C")
            self.assertTrue(crt.enabled)
            tap(run, "C")
            self.assertFalse(crt.enabled)

    def test_a_click_discharges_the_nearest_coil(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            calm_sky(ns)
            bolts = spy_bolts(ns)
            big, small = ns["big"], ns["small"]
            for x, y, coil in ((90, 600, big), (560, 600, small), (1200, 500, small)):
                bolts.clear()
                run.press(x, y)
                run.step(1)
                run.release()
                run.step(1)
                self.assertEqual(len(bolts), 1, (x, y))
                start, end, line = bolts[0]
                self.assertEqual(start, coil.tip())
                self.assertEqual(end, (x, y))
                run.step(SECOND)
                self.assertFalse(line.is_alive, "the discharge stays on screen")


class TestTeslaLightning(unittest.TestCase):
    def tallest_near(self, ns, x):
        things = ns["coils"] + ns["rods"] + ns["houses"]
        near = [t for t in things if abs(t.tip()[0] - x) < 240]
        return max(near, key=lambda t: t.tip()[1]) if near else None

    def test_strikes_hit_the_tallest_thing_in_range(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            calm_sky(ns)
            bolts = spy_bolts(ns)
            st = ns["st"]
            big, small = ns["big"], ns["small"]
            left_rod, right_rod = ns["rods"]
            # a coil, a rod or a house: the tip that stands highest wins
            cases = ((100, big), (300, big), (450, left_rod), (700, right_rod),
                     (1000, right_rod), (1150, ns["houses"][1]))
            for x, target in cases:
                self.assertIs(self.tallest_near(ns, x), target, x)
                bolts.clear()
                charge = st.charge = 0.3
                ns["strike"](x)
                run.step(1)
                self.assertEqual(bolts[0][1], target.tip(), x)
                self.assertLess(abs(bolts[0][0][0] - x), 80 + 1e-6)
                if target in ns["houses"]:
                    self.assertTrue(target.dark)
                    self.assertAlmostEqual(st.charge, charge, delta=0.01)
                else:
                    self.assertAlmostEqual(st.charge, charge + 0.25, delta=0.01,
                                           msg="a coil or a rod does not feed the grid")
                if target in ns["rods"]:
                    self.assertTrue(target.light.visible, "the rod sent nothing down its cable")
            # nothing near the far left edge: no strike
            bolts.clear()
            ns["strike"](-500)
            self.assertEqual(bolts, [])

    def test_the_last_two_strikes_linger_then_dissolve(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            calm_sky(ns)
            bolts = spy_bolts(ns)
            afterimages = ns["afterimages"]
            for x in (100, 450, 700, 1000, 300):
                ns["strike"](x)
                run.step(10)
                self.assertLessEqual(len(afterimages), 2)
            self.assertEqual(len(afterimages), 2)
            lines = [b[2] for b in bolts]
            self.assertEqual(list(afterimages), lines[-2:])
            run.step(SECOND)
            self.assertTrue(all(not line.is_alive for line in lines[:-2]),
                            "a strike that left the afterimages stays on screen")
            # the afterimage: a thin dim line, no longer added light
            self.assertEqual(lines[-1].blend, "normal")
            self.assertEqual(lines[-1].line_width, 2)
            run.step(4 * SECOND)
            self.assertEqual(len(afterimages), 0, "the afterimages never faded")
            self.assertTrue(all(not line.is_alive for line in lines))

    def test_a_struck_house_goes_dark_for_a_while(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            calm_sky(ns)
            # the middle house: the tallest one past the right rod's reach
            house = ns["houses"][1]
            run.step(5 * SECOND)
            self.assertTrue(house.lit)
            ns["strike"](1150)
            run.step(1)
            self.assertTrue(house.dark)
            self.assertFalse(house.lit)
            self.assertEqual(st.lit, 2)
            self.assertEqual(house.spill.amount, 0)
            run.step(SECOND)
            self.assertTrue(all(not w.visible for w in house.windows), "a burned house kept its light")
            # power keeps coming, but the house stays dark until it is repaired
            st.charge = 1
            run.step(7 * SECOND)
            self.assertTrue(house.dark)
            self.assertFalse(house.lit)
            self.assertEqual(st.lit, 2)
            run.step(5 * SECOND)
            self.assertFalse(house.dark, "the house was never repaired")
            self.assertTrue(house.lit, "a repaired house did not light again")
            self.assertEqual(st.lit, 3)

    def test_a_rod_dragged_next_to_a_house_takes_its_strikes(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            calm_sky(ns)
            bolts = spy_bolts(ns)
            rod = ns["rods"][1]
            house = ns["houses"][1]
            ground_y = rod.center.y
            # unguarded, a strike past the right rod's reach burns the middle house
            self.assertIs(self.tallest_near(ns, 1150), house)
            # drag the rod by its pole, up and to the right: it only slides
            x0, y0 = float(rod.center.x), float(rod.center.y)
            run.move(x0, y0)
            run.step(1)
            run.press(x0, y0)
            run.step(1)
            for k in range(1, 21):
                run.move(x0 + (1200 - x0) * k / 20, y0 + 5 * k)
                run.step(1)
                # it follows the pointer sideways only, on every frame
                self.assertAlmostEqual(rod.center.y, ground_y, delta=1e-6, msg="a rod left the ground")
                self.assertAlmostEqual(rod.center.x, x0 + (1200 - x0) * k / 20, delta=1e-6)
            run.release()
            run.step(2)
            # a drag that starts on the sky moves no rod
            others = [float(r.center.x) for r in ns["rods"]]
            run.press(600, 600)
            run.step(1)
            run.move(300, 600)
            run.step(2)
            run.release()
            run.step(1)
            self.assertEqual([float(r.center.x) for r in ns["rods"]], others)
            self.assertAlmostEqual(rod.center.x, 1200, delta=1)
            self.assertAlmostEqual(rod.center.y, ground_y, delta=1e-6, msg="a rod left the ground")
            # its ball and its cable came along (links)
            self.assertEqual(tuple(rod.ball.center), tuple(rod.top_center))
            # the cable's twin buzzes a few units around the wire
            self.assertLess(math.dist(rod.light.at(0), tuple(rod.ball.center)), 8)
            ns["strike"](1150)
            run.step(1)
            self.assertEqual(bolts[-1][1], rod.tip(), "the strike missed the rod")
            self.assertFalse(house.dark, "the rod did not keep the house safe")


if __name__ == "__main__":
    unittest.main()
