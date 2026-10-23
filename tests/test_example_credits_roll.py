"""
The claims of ``examples/credits_roll.py``, played headless.

The example says: the roll opens with the title, then every greet of
GREETS in order, one name at a time (the footer counts ``NN / 15``), then
the finale, and starts again; ``change_act(Card)`` sweeps the last greet away
(its shapes, posts and camera moves); and while a name is on screen its part
performs itself: the History keeps the newest forty dots; each triangle of
the frieze breathes with its own ``base_ratio`` formula; the Concave pieces
follow ``st.rim``; each ``@=`` square follows the one before it; the camera
zooms in to read its own name and comes back; the Bloom turns up with
``st.light``; ``dissolve_out`` spells its name letter by letter; the cast of
the finale stands on its turning ring and runs to the middle.

Three rolls (~300 s of credits, ~4 s headless) feed every check: a greet's
leftovers (a hidden shape never destroyed, a tween on an ``st`` cell that
runs on) show up as a growing count or a warning only in the next roll. One
did: the Concave greet's forever ``tween(st["rim"], …)`` outlived its act
(``st`` is not the act's), kept tweening through the roll, and the next
roll's ``tween(st["rim"], 4)`` replaced it with a warning; the greet now
cancels it before it leaves.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``change_act`` sweeping posts and camera, ``History``
eviction, ``base_ratio`` / ``rim`` / ``angle`` / ``center`` links, camera
tweens, ``Text`` that survives an act change) while it still builds and runs:
``test_scripts_run`` plays only its first 30 frames, before the first greet.

Run:

    python tests/run_tiers.py focused test_example_credits_roll
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

from hypothesis_support import registry  # noqa: E402
from program_support import ProgramRun  # noqa: E402

import scena  # noqa: E402
from scena import canvas, clock  # noqa: E402
from scena.act import get_act_manager  # noqa: E402

PATH = "examples/credits_roll.py"
SECOND = 60
IGNORED = (DeprecationWarning, PendingDeprecationWarning, ResourceWarning)
GREETS = ["track_window", "history", "base_ratio", "concave", "difference", "procession",
          "impacts", "links", "kaleidoscope", "spatial", "camera", "looks", "color_sweep",
          "bloom", "dissolve"]
NAMES = ["Track  begin / end", "History", "Triangle's base_ratio", "Concave",
         'blend = "difference"', "move_along", "the impacts", "@=", "Kaleidoscope",
         "the spatial effects", "the camera", "the looks", "ColorSweep", "Bloom",
         "and to you"]          # dissolve spells its own name, letter by letter
CAST = ["base_ratio", "Fire", "Concave", "Portal", "@=", "Neon", "Orb", "difference",
        "Metal", "Sunburst", "Gel", "History"]


def live(kind):
    return [o for o in registry().live.values() if isinstance(o, kind)]


def xy(p):
    """A point (a Point, or a plain pair) as two floats."""
    if isinstance(p, tuple):
        return float(p[0]), float(p[1])
    return float(p.x), float(p.y)


class Playthrough:
    def __init__(self):
        self.greets = []        # (name, st.number, frame, live count, posts, zoom, rotation, act)
        self.credits = []
        self.footer = {}        # greet name -> the footer's text a second in
        self.footers = set()    # the footer Text objects seen (one, for the whole roll)
        self.failures = []
        self.trails = []        # History lengths in the History greet
        self.checked = {}       # what was checked, how many times
        self.camera_zoom = 0
        self.light_peak = 0
        self.rims = []
        self.dissolved = None
        self.ring = []
        self.leaving = {}       # greet name -> the camera's (zoom, rotation) as it leaves

    def count(self, what, n=1):
        self.checked[what] = self.checked.get(what, 0) + n

    def run(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                self.play(run)
        self.warnings = [str(w.message) for w in caught if not issubclass(w.category, IGNORED)]

    def watch(self, run, fn):
        st = run.ns["st"]
        greets = self.greets

        async def watched():
            greets.append((fn.__name__, st.number, run.frames, len(registry().live),
                           list(canvas.effects), canvas.zoom, canvas.rotation,
                           type(get_act_manager().current).__name__))
            return await fn()

        watched.__name__ = fn.__name__
        return watched

    def play(self, run):
        ns = run.ns
        st = ns["st"]
        ns["GREETS"][:] = [self.watch(run, g) for g in ns["GREETS"]]
        for name in ("opening", "finale"):
            ns[name] = self.watch(run, ns[name])
        credit = ns["credit"]

        def watched_credit(name, note, **kw):
            self.credits.append(name)
            return credit(name, note, **kw)

        ns["credit"] = watched_credit
        drop_dot = ns["drop_dot"]

        def watched_drop_dot(mover, trail):
            drop_dot(mover, trail)
            self.trails.append(len(trail))

        ns["drop_dot"] = watched_drop_dot
        leave = ns["leave"]

        def watched_leave(title):
            self.leaving[self.greets[-1][0]] = (canvas.zoom, canvas.rotation)
            return leave(title)

        ns["leave"] = watched_leave
        light = ns["light"]
        before = st.light
        for _ in range(305 * SECOND):
            run.step(1)
            # update() copies st.light; a tween may write it later in the frame
            if min(abs(light.intensity - st.light), abs(light.intensity - before)) > 1e-9:
                self.failures.append(f"the Bloom at {light.intensity}, st.light {st.light}")
            before = st.light
            if not self.greets:
                continue
            name, _n, start = self.greets[-1][:3]
            if len(self.greets) > 3 * (len(GREETS) + 2):
                return          # the fourth roll has opened
            k = run.frames - start
            if k == SECOND:
                # the counter: the footer's other small line (reading an anchor
                # such as top_right would add its Point to the live roster)
                footer = [t for t in live(scena.Text)
                          if t.font_size == 13 and t.text != "SCENA  ·  END CREDITS"]
                self.footers.update(id(t) for t in footer)
                self.footer[name] = [t.text for t in footer]
            self.check(name, k, ns, st)

    def check(self, name, k, ns, st):
        if name == "base_ratio" and k % 30 == 0 and k > 0:
            for tri in live(scena.Triangle):
                i = round((tri.center.x - 640) / 50 + 9)
                want = 0.7 + 0.55 * math.sin(clock.time * 2.2 - i * 0.4)
                if abs(tri.base_ratio - want) > 1e-6:
                    self.failures.append(f"triangle {i}: base_ratio {tri.base_ratio}, not {want}")
                self.count("triangles")
        elif name == "concave" and k % 10 == 0:
            for piece in live(scena.Concave):
                # rim is a pair (along x, along y); a number sets both
                if max(abs(piece.rim.x - st.rim), abs(piece.rim.y - st.rim)) > 1e-6:
                    self.failures.append(f"a Concave rim at {piece.rim}, st.rim {st.rim}")
                self.count("concave")
            self.rims.append(st.rim)
        elif name == "links" and k % 30 == 0 and k > 0:
            squares = sorted(live(scena.Square), key=lambda s: -s.length)
            self.count("squares", len(squares))
            for before, square in zip(squares, squares[1:]):
                turn = (square.angle - before.angle - 10) % 360
                if min(turn, 360 - turn) > 1e-6 or abs(square.length - 0.86 * before.length) > 1e-6:
                    self.failures.append("an @= square does not follow the one before it")
        elif name == "camera":
            self.camera_zoom = max(self.camera_zoom, canvas.zoom)
        elif name == "bloom":
            self.light_peak = max(self.light_peak, st.light)
        elif name == "dissolve" and k == SECOND:
            letters = [t for t in live(scena.Text) if len(t.text) == 1 and t.font_size == 72]
            self.dissolved = "".join(t.text for t in sorted(letters, key=lambda t: t.center.x))
        elif name == "finale" and k % 15 == 0:
            self.ring.append(st.ring)
            tags = {t.text: t for t in live(scena.Text) if t.font_size == 14 and t.text in CAST}
            ring_place = ns["ring_place"]
            for i, label in enumerate(CAST):
                tag = tags.get(label)
                if tag is None:
                    continue
                want = xy(ring_place(i, len(CAST), below=42))
                if math.dist(xy(tag.center), want) > 1e-6:
                    self.failures.append(f"the {label} tag left its place on the ring")
                self.count("tags")


class TestCreditsRoll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seen = Playthrough()
        cls.seen.run()

    def test_rolls_through_without_a_warning(self):
        self.assertEqual(self.seen.warnings, [])
        self.assertEqual(self.seen.failures, [])

    def test_every_greet_rolls_in_order_and_the_roll_loops(self):
        names = [g[0] for g in self.seen.greets]
        self.assertEqual(names, (["opening"] + GREETS + ["finale"]) * 3 + ["opening"])
        numbers = [g[1] for g in self.seen.greets]
        self.assertEqual(numbers, ([0] + list(range(1, 16)) + [0]) * 3 + [0])
        self.assertEqual(self.seen.credits, NAMES * 3)
        self.assertEqual(self.seen.dissolved, "dissolve_out")
        frames = [g[2] for g in self.seen.greets]
        rolls = frames[::len(GREETS) + 2]
        self.assertEqual(len(rolls), 4)
        for a, b in zip(rolls, rolls[1:]):
            self.assertLess(abs((b - a) / SECOND - 100), 4, "one roll is ~100 s")

    def test_the_footer_counts_the_greets(self):
        self.assertEqual(len(self.seen.footers), 1, "the footer did not stay for the whole roll")
        for i, name in enumerate(GREETS):
            self.assertEqual(self.seen.footer[name], [f"{i + 1:02d} / 15"], name)
        self.assertEqual(self.seen.footer["opening"], [""])
        self.assertEqual(self.seen.footer["finale"], [""])

    def test_each_greet_starts_clean(self):
        """change_act(Card): the last greet's shapes, posts and camera go,
        and nothing piles up from one roll to the next."""
        counts = set()
        for name, _n, _f, count, posts, zoom, rotation, act in self.seen.greets:
            with self.subTest(greet=name):
                self.assertEqual(act, "Card")
                self.assertEqual([type(p).__name__ for p in posts], ["Bloom", "Vignette"])
                self.assertAlmostEqual(zoom, 1)
                self.assertAlmostEqual(rotation % 360, 0)
                counts.add(count)
        self.assertEqual(len(counts), 1, f"a greet's objects outlive it: {counts}")

    def test_the_history_keeps_the_newest_forty(self):
        trails = self.seen.trails
        self.assertGreater(len(trails), 40, "vacuous: no dots dropped")
        self.assertEqual(max(trails), 40)

    def test_the_performers_follow_their_formulas(self):
        checked = self.seen.checked
        self.assertGreater(checked.get("triangles", 0), 19 * 4, "vacuous: no frieze")
        self.assertGreater(checked.get("concave", 0), 4 * 10, "vacuous: no Concave")
        self.assertGreater(checked.get("squares", 0), 10 * 4, "vacuous: no @= squares")
        self.assertGreater(checked.get("tags", 0), 12 * 4, "vacuous: no cast on the ring")

    def test_the_hole_closes_then_breathes(self):
        rims = self.seen.rims
        self.assertEqual(rims[0], 106)
        self.assertAlmostEqual(min(rims), 4, delta=0.5)
        late = rims[len(rims) // 2:]
        self.assertGreater(max(late) - min(late), 10, "the hole does not breathe round the ball")

    def test_the_camera_reads_its_name_and_comes_back(self):
        self.assertAlmostEqual(self.seen.camera_zoom, 2.2, delta=0.01)
        zoom, rotation = self.seen.leaving["camera"]
        self.assertAlmostEqual(zoom, 1)
        self.assertAlmostEqual(rotation % 360, 0)

    def test_the_bloom_turns_up(self):
        self.assertAlmostEqual(self.seen.light_peak, 2.6, delta=0.01)

    def test_the_cast_runs_to_the_middle(self):
        ring = self.seen.ring
        self.assertEqual(ring[0], 1)
        self.assertEqual(min(ring), 0)


if __name__ == "__main__":
    unittest.main()
