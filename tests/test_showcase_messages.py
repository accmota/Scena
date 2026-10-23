"""
The refusals the showcase builders met say what to write instead.

Each case was an author error answered by Python's own words or by a
message that pointed elsewhere (showcase builds, findings B and C,
2026-10-23): ``bloom["intensity"]`` ("not subscriptable"), ``Fire(color=)``
("use visual= on a Sprite"), ``"score" in st`` ("field name must be a str,
got int"), a look's procedural fill passed as a colour ("got
ProceduralFill"), ``track["visible"] @=`` (no reason given),
``await canvas.fade_out(1)`` ("can't be used in 'await' expression").

Bug class guarded: an author spelling that is refused without the spelling
that works.

Run:

    python tests/run_tiers.py focused test_showcase_messages
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from system_support import boot, system_world  # noqa: E402

from scena import (  # noqa: E402
    Bloom, Circle, Fire, Shield, Stars, Track, canvas, st, tween,
)

boot()


class TestShowcaseMessages(unittest.TestCase):
    def refusal(self, call, kind=TypeError) -> str:
        with self.assertRaises(kind) as cm:
            call()
        return str(cm.exception)

    def test_post_and_background_brackets_name_assignment(self):
        with system_world(draw=False):
            bloom = Bloom()
            try:
                msg = self.refusal(lambda: tween(bloom["intensity"], 1, time=1))
                self.assertIn("bloom.intensity = …", msg)
                self.assertIn("update(dt)", msg)
                msg = self.refusal(lambda: Bloom(intensity=lambda: 1.0))
                self.assertIn("bloom.intensity = … in update(dt)", msg)
            finally:
                bloom.remove()
            stars = Stars()
            try:
                self.assertIn("stars.speed = …", self.refusal(lambda: stars["speed"]))
            finally:
                stars.remove()

    def test_fire_color_names_style(self):
        for style in ("camp", "plume"):
            with self.subTest(style=style), system_world(draw=False):
                msg = self.refusal(lambda: Fire(style=style, center=(100, 100), color="cyan"))
                self.assertIn("Fire has no color=", msg)
                self.assertIn("style=", msg)
                self.assertNotIn("Sprite", msg)

    def test_membership_and_iteration_on_st_name_the_methods(self):
        st.score = 1
        self.assertIn("st.exists('score')", self.refusal(lambda: "score" in st))
        self.assertIn("st.keys()", self.refusal(lambda: list(st)))
        self.assertTrue(st.exists("score"))

    def test_a_look_fill_is_not_a_colour(self):
        with system_world(draw=False):
            p = Circle(center=(100, 100), radius=20, visual=Shield("cyan"))
            msg = self.refusal(lambda: canvas.bubbles_at(p, color=p.fill))
            self.assertIn("ProceduralFill", msg)
            self.assertIn(".color", msg)
            canvas.bubbles_at(p, color=p.color)     # the spelling it names works

    def test_track_visible_link_says_why(self):
        with system_world(draw=False):
            t = Track.circle(center=(100, 100), radius=30)
            st.on = True
            msg = self.refusal(lambda: t.__getitem__("visible").__imatmul__(lambda: st.on),
                               AttributeError)
            self.assertIn("draw layer", msg)
            self.assertIn("is a property", msg)
            self.assertIn("track.visible = True", msg)

    def test_awaiting_the_canvas_names_wait_and_on_done(self):
        async def story():
            await canvas.fade_out(0.1)

        coro = story()
        try:
            msg = self.refusal(lambda: coro.send(None))
        finally:
            coro.close()
            canvas.fade_in(0)
        self.assertIn("await wait(seconds)", msg)
        self.assertIn("on_done=", msg)


class TestLineCapNames(unittest.TestCase):
    """0.10.0 Breaking: ``line_cap`` takes the SVG / Skia names. ``"project"``
    drew Skia's butt cap (the flat end that stops at the end point), the
    reverse of Processing's PROJECT; the builders asked for ``"butt"``
    (showcase C). The old spelling raises with the fix, on every door."""

    def test_the_three_ends(self):
        import skia
        from scena import Line
        want = {"round": skia.Paint.Cap.kRound_Cap, "butt": skia.Paint.Cap.kButt_Cap,
                "square": skia.Paint.Cap.kSquare_Cap}
        with system_world(draw=False):
            ln = Line(p1=(10, 10), p2=(90, 10), line_width=8)
            for name, cap in want.items():
                ln.line_cap = name
                self.assertEqual(ln.line_cap, name)
                self.assertEqual(ln._to_skia_line_paint().getStrokeCap(), cap)

    def test_project_raises_with_the_fix(self):
        from scena import Line
        with system_world(draw=False):
            for owner in (Line(p1=(0, 0), p2=(10, 0)), Track.line(p1=(0, 0), length=50, color="white")):
                for spelling in ("project", "PROJECT", " project "):
                    with self.subTest(kind=type(owner).__name__, spelling=spelling):
                        msg = self.refusal(lambda: setattr(owner, "line_cap", spelling))
                        self.assertIn('"butt"', msg)
                        self.assertIn('"square"', msg)
                        self.assertEqual(owner.line_cap, "round")

    refusal = TestShowcaseMessages.refusal


if __name__ == "__main__":
    unittest.main()
