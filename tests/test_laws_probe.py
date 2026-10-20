"""The probe runner (``tests/laws/probe.py``): each flag it raises, on probes
made for it (Testing Design, "Persona probes").

The probes are written to a temporary folder and run once, together
(``run_folder``), each rate in its own process: a game that passes, a wrong
expectation, an author error, an engine-raised error, a hang, frame counting
(E1 and the same check at every rate), typed text, a mirror pair that
holds and one that does not (E11), and the runner's own fixes: drags that
end on time, a fresh folder per run, modifiers named as in ``keyp``.
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from laws import probe  # noqa: E402

COIN = """
from scena import *
init(width=400, height=300, title="probe coin")
score = 0
player = Rect(center=(50, 150), width=20, height=20, group="player")
coin = Circle(center=(200, 150), radius=8, group="coin")


@collide("player", "coin")
def grab(p, c, info):
    global score
    score += 1
    c.destroy()


def update(dt):
    if keyp("RIGHT"):
        player.move_by(200 * dt, 0)


run()
"""

WALKER = """
from scena import *
init(width=400, height=300, title="probe walker")
player = Rect(center=({x}, 150), width=20, height=20)


def update(dt):
    if keyp("RIGHT"):
        player.move_by({right} * dt, 0)
    if keyp("LEFT"):
        player.move_by(-{left} * dt, 0)


run()
"""

PROBES = {
    "coin": (COIN, """
        PLAY = [("wait", 0.2), ("hold", "RIGHT", 1.0), ("wait", 0.3)]
        CHECKS = [("nothing yet", 0.2, lambda g: g.score == 0),
                  ("the coin is taken once", "end", lambda g: g.score == 1)]
    """),
    "wrong": (COIN, """
        HZ = (60,)
        PLAY = [("hold", "RIGHT", 1.2)]
        CHECKS = [("two points", "end", lambda g: g.score == 2)]
        EXPECT_ERROR = ("DestroyedError", "the coin is gone")
    """),
    "author_error": ("""
        from scena import *
        init(width=400, height=300, title="probe author error")
        box = Rect(center=(100, 100), width=10, height=10)


        def update(dt):
            box.move_by(veloctiy * dt, 0)


        run()
    """, """
        HZ = (60,)
        PLAY = [("wait", 0.2)]
        EXPECT_ERROR = ("NameError", "the name I misspelled")
    """),
    "engine_error": ("""
        from scena import *
        init(width=400, height=300, title="probe engine error")


        def update(dt):
            if keyp("SPCE"):
                pass


        run()
    """, """
        HZ = (60,)
        PLAY = [("wait", 0.2)]
    """),
    "hang": ("""
        from scena import *
        init(width=400, height=300, title="probe hang")


        def update(dt):
            while True:
                pass


        run()
    """, """
        HZ = (60,)
        TIMEOUT = 8
        PLAY = [("wait", 0.2)]
    """),
    "frames": ("""
        from scena import *
        init(width=400, height=300, title="probe frame counting")
        frames = 0
        dot = None


        def update(dt):
            global frames, dot
            frames += 1
            if frames == 60:
                dot = Circle(center=(100, 100), radius=5)


        run()
    """, """
        SECONDS = 2.5
        CHECKS = [("the dot after one second", 1.2, lambda g: g.dot is not None)]
    """),
    "typing": ("""
        from scena import *
        init(width=400, height=300, title="probe typing")
        typed = ""


        def on_char(ch):
            global typed
            typed += ch


        run()
    """, """
        HZ = (60,)
        PLAY = [("type", "ab c.1")]
        CHECKS = [("every character arrives", "end", lambda g: g.typed == "ab c.1")]
    """),
    "mirror_ok": (WALKER.format(x=100, right=150, left=150), """
        HZ = (60,)
        PLAY = [("hold", "RIGHT", 0.5), ("hold", "LEFT", 0.2)]
        MIRROR = {"bodies": lambda g: [g.player]}
    """),
    "mirror_bad": (WALKER.format(x=100, right=150, left=150), """
        HZ = (60,)
        PLAY = [("hold", "RIGHT", 0.5)]
        MIRROR = {"bodies": lambda g: [g.player]}
    """),
    "after_drags": ("""
        from scena import *
        init(width=400, height=300, title="probe drags")
        t_space = None


        def update(dt):
            global t_space
            if keyp.once("SPACE") and t_space is None:
                t_space = clock.time


        run()
    """, """
        PLAY = [("drag", 10, 10, 100, 100, 0.3), ("drag", 100, 100, 10, 10, 0.3),
                ("drag", 10, 10, 100, 100, 0.3), ("wait", 0.5), ("tap", "SPACE")]
        CHECKS = [("space lands at 1.4 s", "end",
                   lambda g: g.t_space is not None and abs(g.t_space - 1.4) < 0.05)]
    """),
    "save_file": ("""
        import json, os
        from scena import *
        init(width=400, height=300, title="probe save")
        runs = 1
        if os.path.exists("save.json"):
            with open("save.json") as fh:
                runs = json.load(fh)["runs"] + 1
        with open("save.json", "w") as fh:
            json.dump({"runs": runs}, fh)
        run()
    """, """
        PLAY = [("wait", 0.1)]
        CHECKS = [("a fresh folder each run", "end", lambda g: g.runs == 1)]
    """),
    "modifiers": ("""
        from scena import *
        init(width=400, height=300, title="probe modifiers")
        shift_seen = False
        chord_seen = False


        def update(dt):
            global shift_seen, chord_seen
            shift_seen = shift_seen or keyp("SHIFT")
            chord_seen = chord_seen or keyp("CTRL+S")


        run()
    """, """
        HZ = (60,)
        PLAY = [("hold", "SHIFT", 0.2), ("key_down", "CTRL"), ("tap", "S"), ("key_up", "CTRL"),
                ("wait", 0.1)]
        CHECKS = [("Shift held reads as SHIFT", "end", lambda g: g.shift_seen),
                  ("Ctrl+S reads as the chord", "end", lambda g: g.chord_seen)]
    """),
}
MIRRORS = {
    "mirror_ok": WALKER.format(x=300, right=150, left=150),
    "mirror_bad": WALKER.format(x=300, right=150, left=120),
}


class TestProbeRunner(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="probe_test_")
        folder = cls._tmp.name
        for name, (game, expect) in PROBES.items():
            with open(os.path.join(folder, name + ".py"), "w", encoding="utf-8") as fh:
                fh.write(textwrap.dedent(game).lstrip())
            with open(os.path.join(folder, name + ".expect.py"), "w", encoding="utf-8") as fh:
                fh.write(textwrap.dedent(expect).lstrip())
        for name, game in MIRRORS.items():
            with open(os.path.join(folder, name + ".mirror.py"), "w", encoding="utf-8") as fh:
                fh.write(textwrap.dedent(game).lstrip())
        results = probe.run_folder(folder, os.path.join(folder, "_results"), jobs=4)
        cls.by = {r["probe"][:-3]: r for r in results}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def flags(self, name, prefix=""):
        return [f for f in self.by[name]["flags"] if f.startswith(prefix)]

    def test_every_probe_ran(self):
        self.assertEqual(set(self.by), set(PROBES))
        self.assertTrue(os.path.exists(os.path.join(self._tmp.name, "_results", "summary.md")))

    def test_a_game_that_does_what_it_says_raises_no_flag(self):
        r = self.by["coin"]
        self.assertEqual(r["flags"], [], r["flags"])
        self.assertEqual(set(r["runs"]), {"60", "30", "144"})
        for run in r["runs"].values():
            self.assertTrue(all(c["ok"] for c in run["checks"]), run["checks"])
            self.assertTrue(run["engine"].startswith(probe.ROOT), run["engine"])

    def test_a_wrong_expectation_is_a_flag(self):
        self.assertEqual(len(self.flags("wrong", "CHECK at 60 Hz: 'two points'")), 1,
                         self.by["wrong"]["flags"])
        self.assertEqual(len(self.flags("wrong", "EXPECT_ERROR: expected DestroyedError")), 1)

    def test_an_author_error_names_the_author_line(self):
        (f,) = self.flags("author_error", "ERROR at 60 Hz in play: NameError")
        self.assertIn("innermost author, author author_error.py:7", f)
        self.assertEqual(self.flags("author_error", "EXPECT_ERROR"), [])

    def test_an_engine_raised_error_is_told_apart(self):
        (f,) = self.flags("engine_error", "ERROR at 60 Hz in play:")
        self.assertIn("innermost engine, author engine_error.py:6, engine scena/", f)

    def test_a_hang_is_a_flag_with_its_stack(self):
        (f,) = self.flags("hang", "HANG at 60 Hz")
        self.assertIn("hang.py", f)

    def test_a_hang_stack_keeps_its_innermost_frames(self):
        """faulthandler prints the most recent call first: a long dump keeps
        its head (the author's frame), however long the paths."""
        dump = ("noise\nThread 0x1 (most recent call first):\n"
                '  File "/x/hang.py", line 6 in update\n'
                + '  File "/a/very/long/engine/path/frame.py", line 1 in f\n' * 200)
        self.assertIn("hang.py", probe._hang_stack(dump))

    def test_frame_counting_trips_e1_and_the_same_check_at_every_rate(self):
        self.assertTrue(self.flags("frames", "E1 at 30 Hz"), self.by["frames"]["flags"])
        self.assertTrue(self.flags("frames", "E1 at 144 Hz"), self.by["frames"]["flags"])
        (f,) = self.flags("frames", "PACE: 'the dot after one second'")
        self.assertIn("False at 30 Hz", f)

    def test_typed_text_arrives_character_by_character(self):
        self.assertEqual(self.by["typing"]["flags"], [])

    def test_inputs_after_a_drag_land_at_the_same_game_time_at_every_rate(self):
        self.assertEqual(self.by["after_drags"]["flags"], [])

    def test_each_run_starts_from_a_fresh_copy_of_the_folder(self):
        self.assertEqual(self.by["save_file"]["flags"], [])

    def test_modifiers_named_as_in_keyp_are_held_with_their_bits(self):
        self.assertEqual(self.by["modifiers"]["flags"], [])

    def test_e11_holds_for_a_true_mirror_and_flags_a_false_one(self):
        self.assertEqual(self.by["mirror_ok"]["flags"], [])
        (f,) = self.flags("mirror_bad", "E11: mirror")
        self.assertIn("DU apart", f)


class TestExpectDefaults(unittest.TestCase):

    def write(self, text):
        fd, path = tempfile.mkstemp(suffix=".expect.py")
        with os.fdopen(fd, "w") as fh:
            fh.write(textwrap.dedent(text))
        self.addCleanup(os.remove, path)
        return path

    def test_seconds_default_to_the_play_and_a_half(self):
        e = probe.load_expect(self.write("""
            PLAY = [("wait", 1), ("tap", "A"), ("click", 1, 2), ("type", "abc", 0.2)]
        """))
        self.assertAlmostEqual(e["SECONDS"], 1 + probe.TAP + probe.CLICK + 0.6 + 0.5)
        self.assertEqual(e["HZ"], probe.RATES)
        self.assertTrue(e["LAWS"])

    def test_a_long_session_runs_at_60_hz_without_the_recorder(self):
        e = probe.load_expect(self.write("SECONDS = 3600\n"))
        self.assertEqual(e["HZ"], (60,))
        self.assertFalse(e["LAWS"])


if __name__ == "__main__":
    unittest.main()
