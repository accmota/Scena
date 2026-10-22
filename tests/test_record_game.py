"""tools/video/record_game.py: gameplay videos with sound, rendered offline.

Bug classes guarded:

* **Picture and sound drift apart.** Frame ``i`` of the video and samples
  ``[i*735, (i+1)*735)`` must be the same 1/60 s. Integer frame edges
  (``frame_samples``) keep any run of frames at its exact length, and a sound
  started on the frame something changes colour starts in that frame's block
  (``TestSync``: the colour and the sound come from the same callback).
* **Two clocks advance the voices.** The recorder is the sound card: while it
  is open the mixer is not ``offline`` and the engine's world-time pump
  (``Mixer.pump_dt``) must do nothing, else a sound plays twice as fast and
  ends early (``TestSoundCard``).
* **A frame size the encoder refuses.** 4:2:0 video needs even edges: the
  game is fitted with even edges whatever its design aspect.
* **A take ends at the wrong place.** A pilot ends the run (``game.done``)
  and the take stops after its tail, with sound to the same frame; a take
  that hits its cap first says so (``TestRunEnds``).
* **A stall goes unnoticed.** The review counts still and silent seconds and
  flags a long still stretch, except in the tail after the run is over
  (``TestReview``).
* **The code beside the game is not the program, or does not fit.** The
  code panel drops only the module docstring, and every line fits its
  width and height; the game is drawn right of it (``TestCodePanel``).
* **A build-up marks the wrong lines.** Each step's marked lines are what it
  adds or changes since the step before (none for a step that only
  explains), and every step spec names a real step (``TestBuildup``).
* **The shot list rots, or a pilot does not do what it says.** Every take
  names a program that exists, a pilot that loads and keywords the pilot
  accepts (``TestTakes``). The tutorial-01 tour must reach every feature it
  names, and the catch pilot must catch most and miss some
  (``TestPilotsPlay``: played without drawing). Whole games (Naves, the
  plane) are in ``test_record_game_deep`` (gate).

    python -m unittest tests.test_record_game -v
"""
from __future__ import annotations

import inspect
import os
import random
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "video"))

import record_game as rg  # noqa: E402
import takes as tk  # noqa: E402
from scena.audio_mixer import Mixer, make_sine  # noqa: E402


class TestFrameSamples(unittest.TestCase):
    def test_sixty_fps_is_735_samples_a_frame(self):
        self.assertEqual({rg.frame_samples(i, 44100) for i in range(600)}, {735})
        self.assertEqual({rg.frame_samples(i, 48000) for i in range(600)}, {800})

    def test_any_run_of_frames_has_its_exact_length(self):
        for rate in (44100, 48000, 22050, 11025):
            for start, n in ((0, 1), (7, 13), (59, 61), (1000, 3600)):
                total = sum(rg.frame_samples(i, rate) for i in range(start, start + n))
                self.assertEqual(total, (start + n) * rate // 60 - start * rate // 60)
            self.assertEqual(sum(rg.frame_samples(i, rate) for i in range(60 * 90)), 90 * rate)


class TestFitSize(unittest.TestCase):
    def test_same_aspect_fills_the_frame(self):
        self.assertEqual(rg.fit_size((640, 360), (1920, 1080)), (1920, 1080))

    def test_other_aspect_is_letterboxed(self):
        self.assertEqual(rg.fit_size((600, 480), (1920, 1080)), (1350, 1080))
        self.assertEqual(rg.fit_size((900, 300), (1920, 1080)), (1920, 640))

    def test_edges_are_even(self):
        for design in ((601, 451), (333, 200), (500, 380), (777, 999)):
            for box in ((1920, 1080), (1280, 720), (2560, 1440), (854, 480)):
                w, h = rg.fit_size(design, box)
                self.assertEqual((w % 2, h % 2), (0, 0), (design, box))
                self.assertLessEqual(w, box[0])
                self.assertLessEqual(h, box[1])


class TestSoundCard(unittest.TestCase):
    def _mixer_with_tone(self, seconds):
        m = Mixer()
        m.start_voice(samples=make_sine(440.0, seconds))
        return m

    def test_card_owns_the_clock(self):
        m = self._mixer_with_tone(0.5)
        with rg.SoundCard(m) as card:
            self.assertFalse(m.offline)
            frames = 0
            while m.voices or m.queue._q:
                self.assertIsNone(m.pump_dt(1 / 60))      # the engine's pump: a no-op
                card.pull()
                frames += 1
                self.assertLess(frames, 120)
        self.assertTrue(m.offline)
        self.assertIn(frames, (30, 31))                   # 0.5 s, not 0.25 s
        out = card.samples()
        self.assertEqual(len(out), sum(rg.frame_samples(i, m.sample_rate) for i in range(frames)))
        self.assertGreater(np.abs(out[:735]).max(), 0.1)

    def test_lead_frames_advance_but_are_not_kept(self):
        m = self._mixer_with_tone(1.0)
        with rg.SoundCard(m) as card:
            for _ in range(10):
                card.pull(keep=False)
            card.pull()
        self.assertEqual(card.frame, 11)
        self.assertEqual(len(card.samples()), 735)

    def test_silence_is_a_copy(self):
        m = Mixer()
        with rg.SoundCard(m) as card:
            a, b = card.pull(), card.pull()
        self.assertFalse(np.shares_memory(a, b))


_PING = """\
from scena import *

init(width=160, height=90, title="ping")
Wallpaper("black")
dot = Circle(center=(80, 45), radius=30, color="blue")

def ping():
    dot.color = "red"
    play_sound("synth/coin.wav")

after(0.5, ping)
run()
"""


class _Memory:
    def __init__(self, size, fps):
        self.size, self.fps, self.frames = size, fps, []

    def frame(self, rgba):
        self.frames.append(rgba.copy())

    def finish(self, samples, rate):
        self.samples, self.rate = samples, rate
        return "memory"

    def abort(self):
        pass


class TestSync(unittest.TestCase):
    """A real program, CPU raster: the colour and the sound change together."""

    def _record(self, **kw):
        sinks = []

        def factory(size, fps):
            sinks.append(_Memory(size, fps))
            return sinks[-1]

        r = rg.record("examples/ping.py", factory, source=_PING, size=(320, 180), gpu=False,
                      progress=False, **kw)
        return r, sinks[0]

    def test_sound_starts_in_the_frame_it_is_seen(self):
        r, sink = self._record(seconds=1.0, lead=0.25)
        self.assertEqual(r["frames"], 60)
        self.assertEqual(len(sink.frames), 60)
        self.assertEqual(sink.frames[0].shape, (180, 320, 4))
        self.assertEqual(len(sink.samples), 44100)
        red = [i for i, f in enumerate(sink.frames) if f[90, 160, 0] > 200 and f[90, 160, 2] < 60]
        self.assertTrue(red, "the dot never turned red")
        loud = np.flatnonzero(np.abs(sink.samples).max(axis=1) > 1e-3)
        self.assertTrue(len(loud), "no sound in the take")
        self.assertEqual(int(loud[0]) // 735, red[0])

    def test_thirty_fps_keeps_every_sample(self):
        r, sink = self._record(seconds=0.5, fps=30)
        self.assertEqual(len(sink.frames), 15)
        self.assertEqual(len(sink.samples), 22050)


def _done_at(when):
    def pilot(game, t):
        if t >= when:
            game.done = True
    return pilot


class TestRunEnds(unittest.TestCase):
    def _record(self, pilot, **kw):
        sinks = []

        def factory(size, fps):
            sinks.append(_Memory(size, fps))
            return sinks[-1]

        r = rg.record("examples/ping.py", factory, pilot=pilot, source=_PING, size=(160, 90),
                      gpu=False, progress=False, **kw)
        return r, sinks[0]

    def test_take_stops_a_tail_after_done(self):
        r, sink = self._record(_done_at(0.5), seconds=5.0, tail=0.25)
        self.assertEqual(r["ended"], "done")
        self.assertEqual(len(sink.frames), 30 + 15)
        self.assertEqual(len(sink.samples), 45 * 735)

    def test_done_in_the_lead_keeps_only_the_tail(self):
        r, sink = self._record(_done_at(0.2), seconds=5.0, lead=0.5, tail=0.25)
        self.assertEqual((r["ended"], len(sink.frames)), ("done", 15))
        self.assertEqual(len(sink.samples), 15 * 735)

    def test_cap_before_done(self):
        r, sink = self._record(_done_at(3.0), seconds=0.5)
        self.assertEqual((r["ended"], len(sink.frames)), ("cap", 30))

    def test_thirty_fps_tail(self):
        r, sink = self._record(_done_at(0.5), seconds=5.0, tail=0.5, fps=30)
        self.assertEqual((r["ended"], len(sink.frames)), ("done", 30))
        self.assertEqual(len(sink.samples), 60 * 735)

    def test_pilot_keywords_arrive(self):
        seen = {}

        def pilot(game, t, *, speed, side="left"):
            seen.update(speed=speed, side=side)
            game.done = True

        self._record(pilot, args={"speed": 3}, seconds=1.0, tail=0.0)
        self.assertEqual(seen, {"speed": 3, "side": "left"})


class TestReview(unittest.TestCase):
    def _review(self, moving_seconds, still_seconds, fps=10):
        rv = rg.Review(None, fps, every=1.0, thumb_width=16)
        rng = np.random.default_rng(0)
        still = np.zeros((40, 64, 4), dtype=np.uint8)
        for k in range(moving_seconds * fps):
            rv.frame(rng.integers(0, 255, (40, 64, 4), dtype=np.uint8))
        for k in range(still_seconds * fps):
            rv.frame(still)
        return rv

    def test_still_stretch_is_flagged(self):
        rv = self._review(3, 5)
        rv.finish(np.zeros((8 * 100, 2), np.float32), 100)
        rep = rv.report()
        self.assertEqual((rep["longest_still"], rep["still_at"]), (4, 3))
        self.assertEqual((rep["silent"], rep["heard"]), (8, 8))
        self.assertTrue(any("still" in f for f in rv.flags(rep, ended="cap", expect_end=False)))
        self.assertEqual(len(rv.thumbs), 8)

    def test_tail_after_the_run_is_not_a_stall(self):
        rv = self._review(4, 4)
        rep = rv.report(tail_from=4.0)
        self.assertEqual(rep["longest_still"], 0)
        self.assertEqual(rv.flags(rep, ended="done", expect_end=True), [])

    def test_run_that_never_ends_is_flagged(self):
        rv = self._review(3, 0)
        rep = rv.report()
        self.assertTrue(rv.flags(rep, ended="cap", expect_end=True))
        self.assertEqual(rv.flags(rep, ended="cap", expect_end=False), [])

    def test_meant_still_is_not_a_stall(self):
        """A results screen held on purpose (``game.still``) is not flagged."""
        rv = rg.Review(None, 10, every=1.0, thumb_width=16)
        rng = np.random.default_rng(0)
        for k in range(30):
            rv.frame(rng.integers(0, 255, (40, 64, 4), dtype=np.uint8))
        still = np.zeros((40, 64, 4), dtype=np.uint8)
        for k in range(50):
            rv.mark_meant()
            rv.frame(still)
        rep = rv.report()
        self.assertEqual(rep["longest_still"], 0)
        self.assertEqual(rv.flags(rep, ended="done", expect_end=True), [])

    def test_sound_counts_as_heard(self):
        rv = self._review(2, 0)
        t = np.arange(200) / 100
        rv.finish(np.stack([np.sin(t * 40), np.sin(t * 40)], axis=1).astype(np.float32) * 0.3, 100)
        self.assertEqual(rv.report()["silent"], 0)


def _code_font():
    return next((p for p in rg.CODE_FONTS if os.path.exists(p)), None)


class TestCodePanel(unittest.TestCase):
    """The "this code → this game" layout: the code the viewer reads is the
    program's code, all of it, and it sits beside the game, not over it."""

    def test_program_code_drops_only_the_docstring(self):
        src = '"""Title.\n\nControls.\n"""\n\nfrom scena import *\n\nx = 1  # one\n'
        self.assertEqual(rg.program_code(src), "from scena import *\n\nx = 1  # one\n")
        self.assertEqual(rg.program_code("x = 1\n"), "x = 1\n")

    def test_every_line_fits_the_panel(self):
        if _code_font() is None:
            self.skipTest("no monospace font on this system")
        code = "from scena import *\n" + "\n".join(
            f"v{i} = Rect(center=({i}, {i}), width=90, height=70, color='coral')"
            for i in range(60)) + "\n"
        size = (420, 360)
        panel = rg.code_panel(code, size, title="examples/x.py")
        self.assertEqual(panel.shape, (360, 420, 4))
        ink = np.argwhere((np.abs(panel[..., :3].astype(int) - rg.CODE_BG).sum(axis=2)) > 30)
        self.assertGreater(len(ink), 100, "no text drawn")
        self.assertLess(ink[:, 1].max(), size[0] - 2, "a line runs off the right edge")
        self.assertLess(ink[:, 0].max(), size[1] - 2, "lines run off the bottom")

    def test_game_sits_right_of_the_code(self):
        if _code_font() is None:
            self.skipTest("no monospace font on this system")
        sinks = []

        def factory(size, fps):
            sinks.append(_Memory(size, fps))
            return sinks[-1]

        r = rg.record("examples/ping.py", factory, source=_PING, size=(400, 180), gpu=False,
                      progress=False, seconds=0.1, layout="code")
        frame = sinks[0].frames[-1]
        panel_w = round(400 * rg.CODE_SHARE) // 2 * 2
        self.assertTrue((frame[:, :panel_w, :3] == rg.CODE_BG).any(axis=2).mean() > 0.8)
        gw, gh = r["game_size"]
        self.assertLessEqual(gw, 400 - panel_w)
        # the blue dot of the game is drawn right of the panel
        blue = np.argwhere((frame[..., 2] > 200) & (frame[..., 0] < 80))
        self.assertTrue(len(blue) and blue[:, 1].min() >= panel_w)


class TestBuildup(unittest.TestCase):
    """Build-up videos: a tutorial's steps in order, each marking what it adds."""

    @classmethod
    def setUpClass(cls):
        import buildup
        cls.bu = buildup
        cls.steps = {bid: buildup.page_steps(b["page"]) for bid, b in tk.BUILDUPS.items()}

    def test_steps_and_titles_come_from_the_page(self):
        first = self.steps["primeiro_script"]
        self.assertEqual([n for n, _, _ in first], list(range(1, len(first) + 1)))
        self.assertTrue(all(title for _, title, _ in first))
        self.assertEqual(first[0][1], "A janela")
        self.assertIn("run()", first[-1][2])

    def test_marks_what_a_step_adds_or_changes(self):
        steps = self.steps["primeiro_script"]
        before, after = steps[2][2], steps[3][2]          # 3 Três formas -> 4 Cor
        shown = __import__("record_game").program_code(after).splitlines()
        marked = [shown[k].strip() for k in self.bu.new_lines(before, after)]
        self.assertEqual(marked, ['retangulo.color = "coral"', 'circulo.color = "#FF83FA"',
                                  'triangulo.color = "gold"'])
        first = steps[0][2]
        self.assertEqual(len(self.bu.new_lines("", first)),
                         sum(1 for line in first.splitlines() if line.strip()))
        same = self.steps["pegar_estrelas"]                # 7 Além da tela changes no code
        self.assertEqual(self.bu.new_lines(same[5][2], same[6][2]), [])

    def test_every_step_spec_is_a_step_with_a_pilot(self):
        import inspect
        for bid, b in tk.BUILDUPS.items():
            for n in b["steps"]:
                with self.subTest(buildup=bid, step=n):
                    self.assertTrue(1 <= n <= len(self.steps[bid]))
                    spec = self.bu.step_spec(bid, n)
                    inspect.signature(rg.load_pilot(spec["pilot"])).bind(
                        object(), 0.0, **spec["args"])

    def test_highlight_marks_only_its_lines(self):
        if _code_font() is None:
            self.skipTest("no monospace font on this system")
        code = "a = 1\nb = 2\nc = 3\nd = 4\n"

        def band(**kw):
            panel = rg.code_panel(code, (300, 400), **kw)
            return np.flatnonzero((panel[:, :3, :3] == rg.CODE_MARK_EDGE).all(axis=2).any(axis=1))

        self.assertEqual(len(band()), 0, "no mark without a highlight")
        first, third = band(highlight=[0]), band(highlight=[2])
        for rows in (first, third):
            self.assertTrue(len(rows))
            self.assertEqual(rows.max() - rows.min() + 1, len(rows), "one band")
        self.assertEqual(len(first), len(third))
        self.assertEqual(third.min() - first.min(), 2 * len(first), "two lines lower")


class TestPilotClock(unittest.TestCase):
    def test_at_fires_exactly_once_from_any_start(self):
        """A click timed from a screen's first frame (``t - start``) must land
        on exactly one frame. Compared as seconds, float error made both
        candidate frames miss for some starts: the race pilot never clicked
        the track button (2026-10-22)."""
        import pilots
        for first in range(0, 6000, 7):             # the screen's first frame
            start = first / 60
            for when in (0.5, 1.8, 2.2, 5.0):
                hits = [i for i in range(first, first + 600)
                        if pilots.at(i / 60 - start, when)]
                self.assertEqual(len(hits), 1, (first, when, hits))
                hits = [i for i in range(first, first + 600)
                        if pilots.at(i / 60 - start, when, 3)]
                self.assertEqual(len(hits), 3, (first, when))


class TestTakes(unittest.TestCase):
    def test_every_take_resolves(self):
        import make_readme_media as mm
        blocks = mm.readme_blocks()
        for tid in tk.TAKES:
            with self.subTest(take=tid):
                game, _, name = tid.partition("/")
                self.assertTrue(game and name and "/" not in name, "ids are <game>/<take>")
                spec = tk.take(tid)
                prog = spec["program"]
                if prog.startswith("README.md#"):
                    self.assertIn(prog.split("#", 1)[1], blocks)
                else:
                    self.assertTrue(os.path.isfile(os.path.join(ROOT, prog)), prog)
                fly = rg.load_pilot(spec["pilot"])
                inspect.signature(fly).bind(object(), 0.0, **spec["args"])
                self.assertIn(spec["end"], ("done", "cap"))
                self.assertIn(spec["fps"], (60, 30))
                self.assertEqual([v % 2 for v in spec["size"]], [0, 0])
                self.assertGreater(spec["seconds"], 0)

    def test_last_version_of_a_series(self):
        """A series (naves_1 … naves_6) is shown by its last file only."""
        import re
        from tests.source_support import iter_files
        files = [os.path.basename(p) for p in iter_files(os.path.join(ROOT, "examples"), ".py")]
        last = {}
        for f in files:
            m = re.match(r"([a-z]+)_(\d+)(?:_\w+)?\.py$", f)
            if m:
                last[m.group(1)] = max(last.get(m.group(1), 0), int(m.group(2)))
        for tid in tk.TAKES:
            m = re.match(r"examples/([a-z]+)_(\d+)", tk.take(tid)["program"])
            if m:
                self.assertEqual(int(m.group(2)), last[m.group(1)], tid)

    def test_a_game_picks_all_its_takes(self):
        self.assertEqual(rg.pick_takes(["pegar_estrelas"]),
                         [t for t in tk.TAKES if t.startswith("pegar_estrelas/")])
        self.assertEqual(rg.pick_takes(["primeiro_script/tour"]), ["primeiro_script/tour"])
        with self.assertRaises(SystemExit):
            rg.pick_takes(["no_such_game"])


def _play(tid, seconds, watch=None):
    """Play a take without drawing (until its pilot ends the run or ``seconds``);
    ``watch(ns, t)`` sees every frame. Returns what the tests read, taken
    before the run closes."""
    import make_readme_media as mm
    from program_support import ProgramRun  # type: ignore
    from hypothesis_support import registry  # type: ignore
    spec = tk.take(tid)
    path, source = mm.program_of({"program": spec["program"]})
    random.seed(spec["seed"])
    np.random.seed(spec["seed"])
    run = ProgramRun(path, source=source, seed=spec["seed"], draw=False)
    try:
        run.start()
        game = mm.Pilot(run)
        fly = rg.load_pilot(spec["pilot"])
        before = {k: getattr(run.ns.get(k), "color", None)
                  for k in ("retangulo", "circulo", "triangulo")}
        for i in range(int(seconds * 60)):
            fly(game, i / 60, **spec["args"])
            run.step(1)
            if watch is not None:
                watch(run.ns, (i + 1) / 60)
            if getattr(game, "done", False):
                break
        ns = run.ns
        circles = [o for o in registry().live_objects()
                   if type(o).__name__ == "Circle" and getattr(o, "is_alive", False)]
        out = {"done": getattr(game, "done", False), "before": before,
               "circles": len(circles)}
        if "st" in ns:
            out["st"] = {k: getattr(ns["st"], k, None)
                         for k in ("pontos", "perdidas", "score", "venceu", "vidas", "vencedor",
                                   "estrelas")}
        if "triangulo" in ns:
            out.update(triangle=ns["triangulo"].color, radius=ns["circulo"].radius,
                       colors={k: ns[k].color for k in before})
        return out
    finally:
        run.close(strict=False)


class TestPilotsPlay(unittest.TestCase):
    def test_tour_reaches_every_feature(self):
        r = _play("primeiro_script/tour", 20.5)
        self.assertTrue(r["done"])
        self.assertEqual(r["radius"], 60, "the star never crossed x = 800")
        self.assertTrue(r["triangle"] == "white", r["triangle"])
        for k in ("retangulo", "circulo"):
            self.assertNotEqual(r["colors"][k], r["before"][k], f"{k} was never clicked")
        self.assertEqual(r["circles"] - 1, 8, "D drops one circle per tap")

    def test_catch_pilot_catches_most_and_misses_some(self):
        """Stars fall faster than the bar crosses the screen: even a perfect
        player misses about a fifth, so careful is measured against sloppy."""
        sloppy = _play("pegar_estrelas/sloppy", 40)["st"]       # 2026-10-22: 21 / 19
        careful = _play("pegar_estrelas/careful", 40)["st"]     # 30 / 10
        self.assertGreater(careful["perdidas"], 0)
        self.assertGreaterEqual(careful["pontos"], 2.5 * careful["perdidas"])
        self.assertGreater(sloppy["pontos"], 0.7 * sloppy["perdidas"])
        self.assertGreaterEqual(sloppy["perdidas"], 1.5 * careful["perdidas"],
                                "the two takes must look different")


if __name__ == "__main__":
    unittest.main()
