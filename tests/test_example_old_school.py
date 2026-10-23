"""
The claims of ``examples/old_school.py``, played headless.

The example says: one async script, ``show()``, runs eight parts in this
order (Starfield, Sine scroller, Copper bars, Twister, Rotozoomer, Plasma,
Vector balls, Power off), each with its caption in the corner, and loops
forever; ``change_act(Part)`` clears the last part (its objects, posts and
camera leave together); the title flies in letter by letter and lands in a
row; the greetings ride a sine wave; the logo's History keeps the last 8
ghosts and destroys the older ones; the twister is a square column (two
faces seen at a time, a thin seam between them); the rotozoomer turns and
zooms the whole world; the vector balls are 3D shapes seen in perspective
(nearer balls bigger and on higher layers); the Bloom breathes with the music.

Two loops of the whole storyboard (~197 s of demo, ~10 s headless) feed
every check: a part's leftovers (a hidden shape never destroyed, a tween on
an ``st`` cell that runs on) show up as a growing count or a warning only on
the next loop.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``change_act`` sweeping posts and camera, ``History``
eviction, linked ``center=`` formulas, ``Track`` begin / end links, tweens of
an ``st`` cell) while it still builds and runs: ``test_scripts_run`` plays
only its first 30 frames, before the first part even starts. Also **a part
that raises or warns minutes in** (the storyboard is ~100 s long).

Run:

    python tests/run_tiers.py focused test_example_old_school
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

PATH = "examples/old_school.py"
SECOND = 60
PARTS = ["I  STARFIELD", "II  SINE SCROLLER", "III  COPPER BARS", "IV  TWISTER",
         "V  ROTOZOOMER", "VI  PLASMA", "VII  VECTOR BALLS", "VIII  POWER OFF"]
IGNORED = (DeprecationWarning, PendingDeprecationWarning, ResourceWarning)


def live(kind=None):
    objs = list(registry().live.values())
    return objs if kind is None else [o for o in objs if isinstance(o, kind)]


def xy(p):
    return float(p.x), float(p.y)


class Playthrough:
    """Plays the storyboard twice (into the third loop) and keeps what it saw."""

    def __init__(self):
        self.parts = []             # (caption, clock.time, frame, live count, posts, zoom, rotation, act, caption found)
        self.failures = []          # geometry / link checks that failed: (part, message)
        self.light = []             # the Bloom's intensity, every frame
        self.title = None           # the landed title letters, left to right
        self.scroller_letters = 0
        self.ghost_counts = []      # (History length, live "SCENA" texts) in Copper bars
        self.twister_rows = 0
        self.twister_checked = 0    # rows whose seam was measured
        self.roto_zoom = []
        self.roto_rotation = []
        self.balls_checked = set()  # the morph values (0, 1, 2) whose balls were checked
        self.balls = 0
        self.light_runs = 0

    def run(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                self.play(run)
        self.warnings = [str(w.message) for w in caught if not issubclass(w.category, IGNORED)]

    def play(self, run):
        ns = run.ns
        st = ns["st"]
        new_part = ns["new_part"]

        def watched_part(name):
            new_part(name)
            count = len(registry().live)    # before an anchor read adds its Point
            captions = [t for t in live(scena.Text) if t.text == name]
            found = any(abs(t.top_left.x - 28) < 1e-6 and abs(t.top_left.y - 784) < 1e-6
                        for t in captions)
            self.parts.append((name, clock.time, run.frames, count,
                               list(canvas.effects), canvas.zoom, canvas.rotation,
                               type(get_act_manager().current).__name__, found))

        ns["new_part"] = watched_part
        light = ns["light"]
        for _ in range(205 * SECOND):
            run.step(1)
            self.light.append(light.intensity)
            if not self.parts:
                continue
            name, _t, start = self.parts[-1][:3]
            if len(self.parts) > 2 * len(PARTS):
                if run.frames - start > 2 * SECOND:
                    return          # well into the third loop
                continue
            k = run.frames - start
            if name == PARTS[0]:
                if k == 5 * SECOND:
                    self.check_title(ns)
                if k == 6 * SECOND:
                    self.check_light_runs(ns, st)
            elif name == PARTS[1] and k in (4 * SECOND, 8 * SECOND):
                self.check_scroller(ns, st)
            elif name == PARTS[2] and k > SECOND and k % 15 == 0:
                logos = [t for t in live(scena.Text) if getattr(t, "ghosts", None) is not None]
                if len(logos) != 1:
                    self.failures.append((name, f"{len(logos)} logos with ghosts"))
                    continue
                scena_texts = [t for t in live(scena.Text) if t.text == "SCENA"]
                self.ghost_counts.append((len(logos[0].ghosts), len(scena_texts)))
            elif name == PARTS[3] and k in (2 * SECOND, 5 * SECOND, 9 * SECOND):
                self.check_twister(ns)
            elif name == PARTS[4] and k > SECOND // 2:
                self.roto_zoom.append(canvas.zoom)
                self.roto_rotation.append(canvas.rotation)
            elif name == PARTS[6] and k > SECOND and st.morph in (0, 1, 2) \
                    and st.morph not in self.balls_checked:
                self.check_balls(ns, st)

    # -- the checks, at their moments ---------------------------------------
    def check_title(self, ns):
        letters = sorted((t for t in live(scena.Text) if t.font_size == 110),
                         key=lambda t: t.center.x)
        self.title = "".join(t.text for t in letters)
        homes = [i for i, ch in enumerate("OLD SCHOOL") if ch != " "]
        if len(letters) != len(homes):
            return
        for i, t in zip(homes, letters):
            want = (640 - 4.5 * 104 + i * 104, 440)
            if math.dist(xy(t.center), want) > 0.5:
                self.failures.append((PARTS[0], f"{t.text} landed at {xy(t.center)}, not {want}"))

    def check_light_runs(self, ns, st):
        """The two lights round the frame: begin / end follow their formulas."""
        runs = [t for t in live(scena.Track) if t.line_width == 5]
        self.light_runs = len(runs)
        phase = (clock.time - st.t0) * 0.25
        def ring_gap(a, b):
            gap = abs(a - b) % 1
            return min(gap, 1 - gap)

        starts = set()
        for t in runs:
            start = min((0, 0.5), key=lambda s: ring_gap(t.begin, s + phase))
            starts.add(start)
            for got, want in ((t.begin, (start + phase) % 1), (t.end, (start + 0.18 + phase) % 1)):
                if ring_gap(got, want) > 1e-6:
                    self.failures.append((PARTS[0], f"light run at {got}, its formula says {want}"))
        if starts != {0, 0.5}:
            self.failures.append((PARTS[0], f"the two lights do not run half a lap apart: {starts}"))

    def check_scroller(self, ns, st):
        """Each letter is where scroll_place(i) puts it: on the sine wave,
        sliding left, the right letter of MESSAGE."""
        message = ns["MESSAGE"]
        letters = [t for t in live(scena.Text) if t.font_size == 64]
        self.scroller_letters = len(letters)
        t = clock.time
        for letter in letters:
            x, y = xy(letter.center)
            i = (x - 1320 + ns["SCROLL"] * (t - st.t0)) / ns["SPACING"]
            if abs(i - round(i)) > 1e-6 or message[round(i)] != letter.text:
                self.failures.append((PARTS[1], f"letter {letter.text!r} off its slot ({i})"))
            want = 470 + 110 * math.sin(x * 0.006 + t * 2.6)
            if abs(y - want) > 1e-6:
                self.failures.append((PARTS[1], f"letter {letter.text!r} off the wave"))

    def check_twister(self, ns):
        """Two faces of a square column: side by side, a seam of 2 between them."""
        rows = live(ns["Row"])
        self.twister_rows = len(rows)
        radius, rows_n = ns["RADIUS"], ns["ROWS"]
        for row in rows:
            a, b = row, row.partner
            if min(a.width, b.width) < 1.5:
                continue        # a face edge-on: clamped to 1 unit wide
            self.twister_checked += 1
            la, ra = a.center.x - a.width / 2, a.center.x + a.width / 2
            lb, rb = b.center.x - b.width / 2, b.center.x + b.width / 2
            seam = min(abs(lb - ra), abs(la - rb))
            if abs(seam - 2) > 1e-6:
                self.failures.append((PARTS[3], f"row {row.row}: seam {seam}"))
            # the two faces together are at most the column's diagonal
            if max(ra, rb) - min(la, lb) > 2 * radius + 1e-6:
                self.failures.append((PARTS[3], f"row {row.row} wider than the column"))
            y = 800 * (row.row + 0.5) / rows_n
            if abs(a.center.y - y) > 1e-6 or abs(b.center.y - y) > 1e-6:
                self.failures.append((PARTS[3], f"row {row.row} left its height"))

    def check_balls(self, ns, st):
        """Undo the projection: each ball is on its shape at the right
        distance from the middle, and nearer balls are on higher layers."""
        m = st.morph
        self.balls_checked.add(m)
        balls = live(ns["Ball"])
        self.balls = len(balls)
        shape = {0: "cube", 1: "sphere", 2: "ring"}[m]
        for ball in balls:
            near = ball.radius / 18
            x = (ball.center.x - 640) / (210 * near)
            y = (ball.center.y - 400) / (210 * near)
            z = 4 / near - 4
            want = math.hypot(*getattr(ball, shape))
            if abs(math.sqrt(x * x + y * y + z * z) - want) > 1e-6:
                self.failures.append((PARTS[6], f"a ball left its {shape} ({want})"))
        order = sorted(balls, key=lambda b: b.radius)
        for small, big in zip(order, order[1:]):
            if big.depth < small.depth:
                self.failures.append((PARTS[6], "a nearer ball is drawn behind a farther one"))
                break


class TestOldSchool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seen = Playthrough()
        cls.seen.run()

    def test_plays_through_without_a_warning(self):
        self.assertEqual(self.seen.warnings, [])
        self.assertEqual(self.seen.failures, [])

    def test_the_parts_run_in_the_storyboard_order_and_loop(self):
        names = [p[0] for p in self.seen.parts]
        self.assertEqual(names, PARTS * 2 + [PARTS[0]], "the storyboard order or the loop")
        times = [p[1] for p in self.seen.parts]
        for name, t0, t1 in zip(names, times, times[1:]):
            self.assertGreater(t1 - t0, 5, f"{name} is cut short")
        self.assertLess(abs(times[8] - times[0] - 98.3), 3, "one loop is about 100 s")
        self.assertLess(abs(times[16] - times[8] - 98.3), 3, "one loop is about 100 s")

    def test_each_part_starts_clean_with_its_caption(self):
        """change_act(Part): the last part's objects, posts and camera go,
        and nothing piles up from one loop to the next."""
        light = None
        counts = set()
        for name, _t, _f, count, posts, zoom, rotation, act, caption in self.seen.parts:
            with self.subTest(part=name):
                self.assertTrue(caption, "no caption in the corner")
                self.assertEqual(act, "Part")
                self.assertEqual(len(posts), 1, "a post of the last part stayed")
                light = light or posts[0]
                self.assertIs(posts[0], light, "the Bloom is the demo's, not a part's")
                self.assertAlmostEqual(zoom, 1)
                self.assertAlmostEqual(rotation % 360, 0)
                counts.add(count)
        self.assertEqual(len(counts), 1, f"objects of a part outlive it: {counts}")

    def test_the_title_lands_letter_by_letter(self):
        self.assertEqual(self.seen.title, "OLDSCHOOL")
        self.assertEqual(self.seen.light_runs, 2, "two lights run round the frame")

    def test_the_greetings_ride_the_sine_wave(self):
        self.assertGreater(self.seen.scroller_letters, 50, "vacuous: no scroller letters")

    def test_the_logo_keeps_its_last_eight_ghosts(self):
        counts = self.seen.ghost_counts
        self.assertGreater(len(counts), 20, "vacuous: copper bars not sampled")
        self.assertLessEqual(max(n for n, _ in counts), 8)
        self.assertEqual(max(n for n, _ in counts), 8, "the History never filled")
        # the logo and its ghosts: the History destroyed the older ones
        self.assertLessEqual(max(t for _, t in counts), 9)

    def test_the_twister_is_a_square_column(self):
        self.assertEqual(self.seen.twister_rows, 100)
        self.assertGreater(self.seen.twister_checked, 250, "vacuous: no seam measured")

    def test_the_rotozoomer_turns_and_zooms_the_world(self):
        zoom = self.seen.roto_zoom
        self.assertGreater(len(zoom), 600, "vacuous: rotozoomer not sampled")
        self.assertGreater(max(zoom), 3.4)
        self.assertGreaterEqual(min(zoom), 1 - 1e-6)
        turned = {round(r % 360) // 45 for r in self.seen.roto_rotation}
        self.assertEqual(len(turned), 8, "the world did not turn all the way round")

    def test_the_vector_balls_hold_their_shapes(self):
        self.assertEqual(self.seen.balls, 64)
        self.assertEqual(self.seen.balls_checked, {0, 1, 2},
                         "vacuous: a shape (cube, sphere, ring) was never checked")

    def test_the_bloom_breathes_with_the_music(self):
        light = self.seen.light
        self.assertGreaterEqual(min(light), 0.3 - 1e-9)
        self.assertLessEqual(max(light), 0.9 + 1e-9)
        self.assertGreater(max(light) - min(light), 0.2, "the Bloom does not follow the music")


if __name__ == "__main__":
    unittest.main()
