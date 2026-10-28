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
* **Code too small to read.** A line longer than the panel wraps (inside
  the panel, under its own indent, its mark on every row) rather than
  shrinking the font below ``CODE_MIN_PT``; a step that is still too tall
  folds what it leaves alone to ``…``, never a marked line, and every
  tutorial step and demo chapter reads (``TestCodePanel``, ``TestFit``).
* **A build-up marks the wrong lines.** Each step's marked lines are what it
  adds or changes since the step before (none for a step that only
  explains), and every step spec names a real step; each step opens with
  time to read, its pilot and later captions waiting as long
  (``TestBuildup``). A
  chapter build-up's picks resolve to the program's own code; its panel
  follows the chapters and the last one ends the take (``TestChapters``);
  chained pilots each keep their own clock and memory.
* **A caption is not seen, or says something else than the subtitles.**
  Captions go in the letterbox band above the game (over the game, on a
  dark band, only when that band is too low), fade in and out, fit one
  line; the take reports the spans a caption was on screen and the
  ``.srt`` is made from them, moved by the clips before when steps are
  joined; every ``say`` names a real step or chapter and fits
  (``TestCaptions``).
* **A debug chord arrives as a plain key.** Ctrl+Shift+7 / 6 / 8 over a run
  switch the overlays in turn, each kept as the next comes, and the HUD's
  FPS says the video's rate, not the render's (``TestDebugKeys``).
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
    play_sound("audio/coin.ogg")

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

    def test_a_take_leaves_the_framework_as_it_found_it(self):
        # record() sets the framebuffer metrics and the canvas's pixel ratio
        # for its render and pins its surface: they outlived the take, and
        # every later pixel test of the serial pass drew at 2x into a
        # 320 x 180 surface ("nothing drawn", WP44).
        from scena.orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()

        def state():
            return ({k: getattr(fw, k) for k in ("fb_width", "fb_height", "pixel_ratio", "view_scale",
                                                  "_letterbox_pad_x", "_letterbox_pad_y")},
                    fw._scena_draw.pixel_ratio, "_create_drawing_surface" in vars(fw))
        before = state()
        self._record(seconds=0.1)
        self.assertEqual(state(), before)


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

    def test_a_long_line_wraps_instead_of_shrinking(self):
        if _code_font() is None:
            self.skipTest("no monospace font on this system")
        size = (600, 1200)
        least = round(size[1] * rg.CODE_MIN_PT)
        code = "x = 1\n    " + " + ".join(f"value_{i}" for i in range(30)) + "\ny = 2\n"
        pt, rows = rg.code_fit(code, size)
        self.assertGreaterEqual(pt, least)
        self.assertGreater(len(rows), 3, "the long line wraps")
        self.assertEqual([n for n, _ in rows].count(1), len(rows) - 2)
        text = ["".join(p for _, p in toks) for _, toks in rows]
        self.assertEqual("".join(t.strip() for t in text[1:-1]).replace(" ", ""),
                         code.splitlines()[1].replace(" ", ""), "nothing lost or doubled")
        self.assertTrue(all(t.startswith(" " * 8) for t in text[2:-1]), "rest under its indent")
        panel = rg.code_panel(code, size)
        ink = np.argwhere((np.abs(panel[..., :3].astype(int) - rg.CODE_BG).sum(axis=2)) > 30)
        self.assertLess(ink[:, 1].max(), size[0] - 2, "a row runs off the right edge")
        panel = rg.code_panel(code, size, highlight=[1])
        marks = np.flatnonzero((panel[:, :3, :3] == rg.CODE_MARK_EDGE).all(axis=2).any(axis=1))
        step = round(pt * 1.35)
        self.assertGreaterEqual(len(marks), (len(rows) - 2) * step - 2, "every row marked")

    def test_code_can_change_during_a_take(self):
        """``code_at``: the panel follows the take, and may end it."""
        if _code_font() is None:
            self.skipTest("no monospace font on this system")
        sinks = []

        def code_at(game, t):
            if t >= 0.3:
                game.done = True
            return ("a = 1\n", "first", ()) if t < 0.2 else ("b = 2\n" * 6, "second", (0,))

        r = rg.record("examples/ping.py", lambda size, fps: sinks.append(_Memory(size, fps))
                      or sinks[-1], source=_PING, size=(400, 180), gpu=False, progress=False,
                      seconds=5.0, tail=0.2, layout="code", code_at=code_at)
        frames = sinks[0].frames
        panel_w = round(400 * rg.CODE_SHARE) // 2 * 2
        self.assertEqual(r["ended"], "done")
        self.assertLess(len(frames), 40)
        first, last = frames[0][:, :panel_w], frames[-1][:, :panel_w]
        self.assertFalse((first == last).all(), "the panel changed")
        self.assertFalse((first[:, :3, :3] == rg.CODE_MARK_EDGE).all(axis=2).any())
        self.assertTrue((last[:, :3, :3] == rg.CODE_MARK_EDGE).all(axis=2).any())
        with self.assertRaises(ValueError):
            rg.record("examples/ping.py", lambda size, fps: _Memory(size, fps), source=_PING,
                      code_at=code_at)

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
        cls.steps = {bid: buildup.page_steps(b["page"], b.get("example"))
                     for bid, b in tk.BUILDUPS.items() if "page" in b}

    def test_steps_and_titles_come_from_the_page(self):
        first = self.steps["first_script"]
        self.assertEqual([n for n, _, _ in first], list(range(1, len(first) + 1)))
        self.assertTrue(all(title for _, title, _ in first))
        self.assertEqual(first[0][1], "The window")
        self.assertIn("run()", first[-1][2])
        self.assertEqual(self.bu.step_word(tk.BUILDUPS["first_script"]["page"]), "Step")
        self.assertEqual(self.bu.step_word("docs/pt/tutorial/01-primeiro-script.html"), "Passo")

    def test_a_page_with_two_programs_splits(self):
        """30-spins ends in the bars, then the oscilloscope: each build-up gets
        its own steps, numbered from 1."""
        bars, osc = self.steps["spinning_bars"], self.steps["oscilloscope"]
        page = len(self.bu.page_steps(tk.BUILDUPS["oscilloscope"]["page"]))
        self.assertEqual(len(bars) + len(osc), page)
        self.assertIn("spin_factor", bars[-1][2])
        self.assertEqual(osc[0][0], 1)
        self.assertNotIn("spin_factor", osc[0][2])
        self.assertIn("switched_on", osc[-1][2])

    def test_marks_what_a_step_adds_or_changes(self):
        steps = self.steps["first_script"]
        before, after = steps[2][2], steps[3][2]          # 3 Three shapes -> 4 Color
        shown = __import__("record_game").program_code(after).splitlines()
        marked = [shown[k].strip() for k in self.bu.new_lines(before, after)]
        self.assertEqual(marked, ['rectangle.color = "coral"', 'circle.color = "#FF83FA"',
                                  'triangle.color = "gold"'])
        first = steps[0][2]
        self.assertEqual(len(self.bu.new_lines("", first)),
                         sum(1 for line in first.splitlines() if line.strip()))
        same = self.steps["catch_stars"]                   # 7 Off the screen: no new code
        self.assertEqual(self.bu.new_lines(same[5][2], same[6][2]), [])

    def test_every_step_spec_is_a_step_with_a_pilot(self):
        import inspect

        def binds(pilot, args):
            inspect.signature(rg.load_pilot(pilot)).bind(object(), 0.0, **args)
            if pilot == "with_debug_keys":
                binds(args["pilot"], args.get("args", {}))

        for bid in self.steps:
            b = tk.BUILDUPS[bid]
            for n in b["steps"]:
                with self.subTest(buildup=bid, step=n):
                    self.assertTrue(1 <= n <= len(self.steps[bid]))
                    spec = self.bu.step_spec(bid, n)
                    binds(spec["pilot"], spec["args"])
                    binds(spec["reader"], spec["reader_args"])
            if b.get("finale", {}).get("pilot"):
                with self.subTest(buildup=bid, finale=True):
                    binds(b["finale"]["pilot"], b["finale"].get("args", {}))

    def test_every_build_up_plays_on_after_its_code(self):
        """The last step plays on: a pilot of its own, or one that is not a
        short timetable (a tour stops moving when its script ends)."""
        for bid in self.steps:
            with self.subTest(buildup=bid):
                b = tk.BUILDUPS[bid]
                last = self.bu.step_spec(bid, len(self.steps[bid]))
                self.assertTrue(b.get("finale", {}).get("pilot")
                                or last["pilot"] not in ("tour", "watch"))
        self.assertGreaterEqual(self.bu.FINALE, 5)
        self.assertLessEqual(self.bu.FINALE, 10)

    def test_each_step_opens_with_time_to_read(self):
        """A step's pilot waits while the viewer reads its caption and new
        lines; a later caption waits as long (it is timed to the pilot), and
        the build-ups grow by 30-50 % in all."""
        rt = self.bu.reading_time
        self.assertEqual(rt("", 0), self.bu.READ_BASE)
        self.assertGreater(rt("one two three four five six", 0), rt("one two", 0))
        self.assertGreater(rt("x", 8), rt("x", 1))
        self.assertEqual(rt("word " * 50, 50), self.bu.READ_MAX)
        n = next(n for n, _, code in self.steps["ships_1"] if "@leave_playfield" in code)
        read = self.bu.step_read("ships_1", n)
        cue_list, _ = self.bu.step_cues("ships_1", n)
        said = tk.BUILDUPS["ships_1"]["say"][n]
        self.assertEqual(cue_list[0][0], 0.0)
        self.assertEqual([t for t, _ in cue_list[1:]], [t + read for t, _ in said[1:]])
        before = after = 0.0
        for bid, steps in self.steps.items():
            for n, _, _ in steps:
                spec = self.bu.step_spec(bid, n)
                before += spec["seconds"]
                after += spec["seconds"] + self.bu.step_read(bid, n)
        self.assertTrue(1.3 <= after / before <= 1.5, after / before)

    def test_a_step_brings_its_lines_with_its_captions(self):
        """Ships step 14 says "A burst for each hit", then "And a score": the
        score's lines come with the second caption (not shown before it, and
        marked then), the burst's with the first, and the scoreboard stays off
        the game's screen until its lines are in."""
        first, second = self.bu.step_stages("ships_1", 14)
        lines1, lines2 = first[1].splitlines(), second[1].splitlines()
        self.assertEqual([lines1[k].strip() for k in first[2]],
                         ["canvas.burst_at(enemy, radius=40)"])
        self.assertFalse(any("score" in line for line in lines1))
        self.assertTrue(all("score" in lines2[k] for k in second[2]))
        self.assertEqual(len(second[2]), 4)
        self.assertNotIn(lines2.index("    canvas.burst_at(enemy, radius=40)"), second[2])
        self.assertEqual((first[3], second[3]), ({"scoreboard"}, set()))
        cue_list, _ = self.bu.step_cues("ships_1", 14)
        self.assertEqual(second[0], cue_list[1][0], "the lines come with their caption")
        self.assertEqual(self.bu.step_read("ships_1", 14),
                         self.bu.reading_time("A burst for each hit", 1))
        one = self.bu.step_stages("ships_1", 13)
        self.assertEqual(len(one), 1)
        self.assertEqual(one[0][3], set())

    def test_leave_playfield_is_shown_in_debug_view(self):
        """Ships step 7 (@leave_playfield): hitboxes and the debug zoom on,
        then off again before the step ends (the chords toggle and cycle)."""
        steps = self.steps["ships_1"]
        n = next(n for n, _, code in steps if "@leave_playfield" in code)
        spec = self.bu.step_spec("ships_1", n)
        self.assertEqual(spec["pilot"], "with_debug_keys")
        keys = [k for when, k in spec["args"]["chords"] if when < spec["seconds"]]
        self.assertEqual(keys.count("7") % 2, 0, "hitboxes off again")
        self.assertEqual(keys.count("8") % 3, 0, "zoom back to 100 % (100, 50, 25)")
        self.assertGreater(keys.count("8"), 0)

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


class TestFit(unittest.TestCase):
    """What the panel shows when a program is too long to read whole."""

    @classmethod
    def setUpClass(cls):
        import buildup
        cls.bu = buildup

    def test_short_code_is_whole(self):
        code = "from scena import *\n\ndef f():\n    a = 1\n    b = 2\n    c = 3\n\nrun()\n"
        self.assertEqual(self.bu.fit(code, [3]), (code, [3]))

    def test_folds_what_the_step_leaves_alone(self):
        if _code_font() is None:
            self.skipTest("no monospace font on this system")
        body = "".join(f"    v{i} = {i}\n" for i in range(30))
        code = ("from scena import *\n\ninit(width=100, height=100)\n"
                + "".join(f"r{i} = Rect()\n" for i in range(10))
                + "\n\ndef old():\n" + body + "\n\ndef new():\n" + body + "\n\nrun()\n")
        lines = code.splitlines()
        marked = [k for k, line in enumerate(lines) if line.startswith("def new")]
        marked += [marked[0] + 3]
        shown, marks = self.bu.fit(code, marked, "Step 2 · New")
        out = shown.splitlines()
        self.assertEqual([out[k] for k in marks], [lines[k] for k in marked], "marks follow")
        self.assertIn("def old():", out)
        self.assertEqual(out[out.index("def old():") + 1], "    …", "the untouched body folds")
        self.assertIn("run()", out)
        self.assertIn("from scena import *", out)
        self.assertGreaterEqual(rg.code_fit(shown, self.bu.panel_size(), "Step 2 · New")[0],
                                round(self.bu.panel_size()[1] * rg.CODE_MIN_PT))

    def test_every_tutorial_step_reads(self):
        if _code_font() is None:
            self.skipTest("no monospace font on this system")
        size = self.bu.panel_size()
        least = round(size[1] * rg.CODE_MIN_PT)
        for bid, b in tk.BUILDUPS.items():
            if "page" not in b:
                continue
            steps = self.bu.page_steps(b["page"], b.get("example"))
            for n, title, code in steps:
                with self.subTest(buildup=bid, step=n):
                    before = steps[n - 2][2] if n > 1 else ""
                    heading = f"Step {n} · {title}"
                    marked = self.bu.new_lines(before, code)
                    shown, marks = self.bu.fit(rg.program_code(code), marked, heading)
                    self.assertEqual(len(marks), len(marked), "a marked line folded")
                    self.assertGreaterEqual(rg.code_fit(shown, size, heading)[0], least - 1)


class TestChapters(unittest.TestCase):
    """Chapter build-ups: a demo's run, the code of the part on screen."""

    @classmethod
    def setUpClass(cls):
        import buildup
        cls.bu = buildup

    SRC = ('"""Doc."""\nfrom scena import *\n\nN = 3\nM = 4\n\n\n'
           '# ---- part one ----\n\n# the stars\ndef stars(n):\n    """Doc."""\n'
           '    a = n\n    return a\n\n\nclass Ball(Circle):\n    """A ball."""\n\n'
           '    def setup(self):\n        self.v = 0\n\n    def on_update(self, dt):\n'
           '        self.v += dt\n\n\nasync def show():\n    await wait(1)\n'
           '    while True:\n        # one\n        stars(1)\n        # two\n'
           '        stars(2)\n        # three\n        stars(3)\n\n\nrun_task(show)\nrun()\n')

    def test_excerpt_picks_slices_and_folds(self):
        ex = self.bu.excerpt
        self.assertEqual(ex(self.SRC, ("N", "M")), "N = 3\nM = 4\n")
        self.assertEqual(ex(self.SRC, ("stars",)),
                         '# the stars\ndef stars(n):\n    """Doc."""\n    a = n\n    return a\n')
        self.assertEqual(ex(self.SRC, ("stars", "N"), ("stars",)),
                         "# the stars\ndef stars(n): …\n\nN = 3\n")
        self.assertEqual(ex(self.SRC.replace("# the stars\n", ""), ("stars", "N"), ("stars",)),
                         "def stars(n): …\nN = 3\n", "one-line blocks stack")
        self.assertEqual(ex(self.SRC, ("Ball",), ("Ball.__doc__", "Ball.setup")),
                         "class Ball(Circle):\n    def setup(self): …\n\n"
                         "    def on_update(self, dt):\n        self.v += dt\n")
        self.assertEqual(ex(self.SRC, (("show", "# two", "# three"),)),
                         "async def show():\n        …\n        # two\n        stars(2)\n"
                         "        …\n")
        self.assertEqual(ex(self.SRC, (("show", "# three", None), "run_task", "run")),
                         "async def show():\n        …\n        # three\n        stars(3)\n"
                         "\nrun_task(show)\nrun()\n")
        with self.assertRaises(ValueError):
            ex(self.SRC, ("nothing",))

    def test_every_chapter_reads(self):
        if _code_font() is None:
            self.skipTest("no monospace font on this system")
        size = self.bu.panel_size()
        least = round(size[1] * rg.CODE_MIN_PT)
        for bid, b in tk.BUILDUPS.items():
            if "chapters" not in b:
                continue
            panels = self.bu.chapter_panels(bid)
            self.assertEqual(len(panels), len(b["chapters"]))
            self.assertGreaterEqual(len(panels), 2)
            for code, title, _ in panels:
                with self.subTest(buildup=bid, chapter=title):
                    compile(code.replace("…", "pass"), title, "exec")
                    self.assertGreaterEqual(rg.code_fit(code, size, title)[0], least - 2)

    def test_chain_keeps_each_pilot_apart(self):
        import pilots
        seen = []

        def first(game, t):
            pilots.memo(game).setdefault("who", "first")
            seen.append(("first", round(t, 2), pilots.memo(game)["who"]))

        def second(game, t):
            pilots.memo(game).setdefault("who", "second")
            seen.append(("second", round(t, 2), pilots.memo(game)["who"]))

        class Game:
            pass

        game = Game()
        saved = dict(pilots.PILOTS)
        pilots.PILOTS.update(first=first, second=second)
        try:
            for t in (0.0, 0.5, 1.0, 1.5):
                pilots.chain(game, t, parts=((0.0, "first", {}), (1.0, "second", {})))
        finally:
            pilots.PILOTS.clear()
            pilots.PILOTS.update(saved)
        self.assertEqual(seen, [("first", 0.0, "first"), ("first", 0.5, "first"),
                                ("second", 0.0, "second"), ("second", 0.5, "second")])
        self.assertNotIn("who", pilots.memo(game), "the chain's own memory stays apart")


class TestCaptions(unittest.TestCase):
    """What a build-up says on screen, and its subtitles."""

    @classmethod
    def setUpClass(cls):
        import buildup
        cls.bu = buildup

    def test_box_is_the_band_above_the_game(self):
        self.assertEqual(rg.caption_box((2560, 1440), ((1024, 105), (1536, 1229))),
                         (0, 105, 1024, 2560, False))
        top, bottom, left, right, over = rg.caption_box((2560, 1440), ((1024, 20), (1536, 1400)))
        self.assertTrue(over)
        self.assertEqual((top, left, right), (20, 1024, 2560))
        self.assertGreater(bottom - top, 40)

    def test_timeline_fades_and_hands_over(self):
        say = self.bu.timeline([(0.0, "one"), (2.0, "two")], 4.0)
        self.assertEqual(say(1.0), ("one", 1.0))
        self.assertEqual(say(0.0), ("one", 0.0))
        text, alpha = say(1.9)
        self.assertEqual(text, "one")
        self.assertLess(alpha, 1.0)
        self.assertEqual(say(3.0)[0], "two")
        self.assertIsNone(say(4.0))
        held = self.bu.timeline([(1.0, "on")], None)
        self.assertEqual(held(100.0), ("on", 1.0))
        self.assertIsNone(held(0.5))

    def test_srt_and_joined_steps(self):
        spans = self.bu.joined_captions([
            {"captions": [(0.0, 2.5, "A")], "length": 3.0},
            {"captions": [(0.5, 1.0, "B"), (1.5, 2.0, "C")], "length": 2.0}])
        self.assertEqual(spans, [(0.0, 2.5, "A"), (3.5, 4.0, "B"), (4.5, 5.0, "C")])
        self.assertEqual(self.bu.srt([(0.0, 2.5, "A"), (3725.25, 3726.0, "B")]),
                         "1\n00:00:00,000 --> 00:00:02,500\nA\n\n"
                         "2\n01:02:05,250 --> 01:02:06,000\nB\n\n")

    def test_take_draws_and_reports_its_captions(self):
        sinks = []

        def say(game, t):
            return ("Hello", 1.0) if 0.5 <= t < 1.0 else None

        r = rg.record("examples/ping.py", lambda size, fps: sinks.append(_Memory(size, fps))
                      or sinks[-1], source=_PING, size=(400, 400), gpu=False, progress=False,
                      seconds=1.5, layout="code", caption_at=say)
        self.assertEqual(len(r["captions"]), 1)
        a, b, text = r["captions"][0]
        self.assertEqual(text, "Hello")
        self.assertAlmostEqual(a, 0.5, delta=0.02)
        self.assertAlmostEqual(b, 1.0, delta=0.02)
        top, bottom, left, right, over = rg.caption_box(
            (400, 400), ((400 - r["game_size"][0], (400 - r["game_size"][1]) // 2),
                         r["game_size"]))
        frames = sinks[0].frames

        def lit(frame):
            return int((frame[top:bottom, left:right, :3] > 200).all(axis=2).sum())

        self.assertEqual(lit(frames[10]), 0)
        self.assertGreater(lit(frames[45]), 20, "the caption is drawn")
        self.assertEqual(lit(frames[-1]), 0, "and cleared when it is over")

    def test_every_say_is_a_step_or_chapter_and_fits(self):
        from PIL import ImageFont
        w, h = tk.DEFAULTS["size"]
        game_w = w - round(w * rg.CODE_SHARE) // 2 * 2
        font = ImageFont.truetype(str(rg.CAPTION_FONT), round(h * rg.CAPTION_PT))
        for bid, b in tk.BUILDUPS.items():
            count = (len(b["chapters"]) if "chapters" in b
                     else len(self.bu.page_steps(b["page"], b.get("example"))))
            for k, say in b.get("say", {}).items():
                with self.subTest(buildup=bid, say=k):
                    self.assertTrue(k == "finale" and "page" in b or 1 <= k <= count)
                    for _, text in self.bu.cues(say):
                        self.assertLessEqual(font.getlength(text.format(lines=999)),
                                             game_w * 0.94, "one line at full size")
            if "page" in b:
                for n in range(1, count + 1):
                    cue_list, end = self.bu.step_cues(bid, n)
                    self.assertTrue(all(0 <= t < end for t, _ in cue_list))
                    self.assertEqual([t for t, _ in cue_list], sorted(t for t, _ in cue_list))


class TestDebugKeys(unittest.TestCase):
    """Debug-mode takes: each chord reaches the engine as Ctrl+Shift+digit
    (the modifiers go down first: keys of one frame arrive in name order, and
    a "7" before its Ctrl and Shift is a plain 7), and an earlier overlay
    stays on when the next one comes."""

    def test_chords_switch_the_overlays_in_turn(self):
        import pilots
        from scena import process_overlay
        seen = {}

        def pilot(game, t):
            pilots.with_debug_keys(game, t, pilot="watch",
                                   chords=((0.5, "7"), (1.0, "6"), (1.5, "8")))
            fw = game.run.world.fw
            for when in (0.9, 1.4, 1.9):
                if abs(t - when) < 1 / 120:
                    seen[when] = (fw._overlay_pack, process_overlay.processes_overlay_level(),
                                  fw._debug_zoom)

        sinks = []
        try:
            rg.record("examples/ping.py", lambda size, fps: sinks.append(_Memory(size, fps))
                      or sinks[-1], pilot=pilot, source=_PING, size=(160, 90), gpu=False,
                      progress=False, seconds=2.0)
        finally:
            # These switches live on the framework, not the world: left on, the
            # next test's clicks land through a 50 % view (each take runs in a
            # process of its own, so a recording never inherits them).
            from scena.orchestration import ScenaFramework
            fw = ScenaFramework.get_instance()
            if fw._overlay_pack:
                fw._toggle_overlay_pack()
            fw._set_debug_zoom(1.0)
            if process_overlay.processes_overlay_level():
                process_overlay.show_processes(False)
        self.assertEqual(seen, {0.9: (True, 0, 1.0), 1.4: (True, 1, 1.0), 1.9: (True, 1, 0.5)})

    def test_the_hud_reports_the_video_rate(self):
        """Offline, frames per wall-clock second is the render's speed: the
        HUD's FPS must say what the video plays at."""
        rates = []

        def pilot(game, t):
            rates.append(game.run.world.fw.clock.fps)

        rg.record("examples/ping.py", lambda size, fps: _Memory(size, fps), pilot=pilot,
                  source=_PING, size=(160, 90), gpu=False, progress=False, seconds=0.5)
        self.assertEqual(set(rates[1:]), {float(rg.GAME_FPS)})


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
    from program_support import run_registry  # type: ignore
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
        circles = [o for o in run_registry().live_objects()      # the program's (WP42)
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

    def test_ships_last_step_lives_until_its_finale(self):
        """Ships' last step: the ship lives while the viewer reads (its reader
        dodges; idle under the fleet's fire it was shot down before its pilot
        began) and through the step, and is hit in the finale."""
        import buildup
        from program_support import ProgramRun  # type: ignore
        import make_readme_media as mm
        steps = buildup.page_steps(tk.BUILDUPS["ships_1"]["page"])
        n = len(steps)
        pilot, args, seconds, ends = buildup.step_pilot("ships_1", n)
        random.seed(n)
        np.random.seed(n)
        run = ProgramRun(tk.BUILDUPS["ships_1"]["program"], source=steps[-1][2], seed=n,
                         draw=False)
        alive = {}
        try:
            run.start()
            game, fly = mm.Pilot(run), rg.load_pilot(pilot)
            for i in range(int(seconds * 60)):
                fly(game, i / 60, **args)
                run.step(1)
                alive[i] = bool(run.ns["ship"])
        finally:
            run.close(strict=False)
        self.assertTrue(alive[int(ends * 60) - 1], "shot down before the finale")
        self.assertFalse(alive[max(alive)], "never hit: the new @collide is not seen")

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
