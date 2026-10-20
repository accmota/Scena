"""An unknown read names the fix (persona probes PP, 0.9.0).

Bug class: a read of a name the object does not have (``chave.hide()``,
``bola.transform``, ``clock.tick(60)``) raised Python's bare "object has no
attribute", or a suggestion of a private engine name (``Did you mean:
'_tick'?``). Writes already named the fix (``bola.velocity = …`` → "Scena
spells it 'vel'"); reads now do too: the names other engines and Scratch use,
a field another kind owns, a close public name. A miss that nobody prints
(``hasattr``, ``getattr(x, name, None)``) builds no message.

    python tests/run_tiers.py focused test_read_hints
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena import Circle, Entity, Rect, Sprite, Text, clock, init  # noqa: E402


def _read_error(obj, name) -> str:
    try:
        getattr(obj, name)
    except AttributeError as e:
        return str(e)
    raise AssertionError(f"{name} read without error")


class TestEntityReads(unittest.TestCase):

    def setUp(self):
        init(width=400, height=300)
        self.c = Circle(center=(50, 50), radius=10)
        self.addCleanup(self.c.destroy)

    def test_names_from_other_engines_and_scratch(self):
        for name, fix in (("hide", "visible = False"), ("show", "visible = True"),
                          ("kill", "destroy()"), ("remove", "destroy()"),
                          ("transform", ".center"), ("position", ".center"),
                          ("goto", "move_to("), ("glide", "time="),
                          ("point_towards", "heading("), ("look_at", "heading(")):
            msg = _read_error(self.c, name)
            self.assertIn(fix, msg, name)
            self.assertIn("Circle", msg, name)

    def test_a_field_another_kind_owns(self):
        self.assertIn("set_alpha", _read_error(self.c, "alpha"))
        self.assertIn("(a Text field)", _read_error(self.c, "font_size"))

    def test_a_close_public_name(self):
        self.assertIn("'radius'", _read_error(self.c, "raidus"))
        self.c.vidas = 3
        self.assertIn("'vidas'", _read_error(self.c, "vida"))

    def test_scenas_own_spelling(self):
        self.assertIn("'vel'", _read_error(self.c, "velocity"))

    def test_never_a_private_name(self):
        for name in ("tick", "rgistry", "constructed"):
            msg = _read_error(self.c, name)
            self.assertNotIn("'_", msg, name)

    def test_a_plain_miss_keeps_the_python_words(self):
        self.assertIn("'Circle' object has no attribute 'zzqx'", _read_error(self.c, "zzqx"))

    def test_a_traceback_names_attribute_error(self):
        import traceback
        try:
            self.c.hide()
        except AttributeError as e:
            text = "".join(traceback.format_exception_only(type(e), e))
        self.assertTrue(text.startswith("AttributeError: "), text)
        self.assertNotIn("_UnknownRead", text)

    def test_an_own_field_never_set_gets_no_far_fetched_hint(self):
        self.assertNotIn("'vel'", _read_error(self.c, "nivel"))

    def test_hasattr_and_getattr_default_still_work(self):
        self.assertFalse(hasattr(self.c, "hide"))
        self.assertIsNone(getattr(self.c, "hide", None))
        e = Entity()
        self.addCleanup(e.destroy)
        self.assertFalse(hasattr(e, "transform"))


class TestClockReads(unittest.TestCase):

    def test_tick_names_the_frame_loop_not_a_private_method(self):
        msg = _read_error(clock, "tick")
        self.assertNotIn("_tick", msg)
        self.assertIn("update(dt)", msg)
        self.assertIn("framerate", msg)

    def test_a_close_public_name(self):
        self.assertIn("'time'", _read_error(clock, "tme"))
        self.assertNotIn("'_", _read_error(clock, "tme"))

    def test_private_misses_stay_plain(self):
        self.assertFalse(hasattr(clock, "_no_such_thing"))


class TestPositionalTime(unittest.TestCase):
    """``move_to(1, 200, 100)`` (Scratch's "glide 1 s to x, y") got Python's
    "takes from 1 to 3 positional arguments but 4 were given": the count
    holds ``self``, and nothing says ``time=`` (persona probes PP). Every pose
    verb names the keyword, with the call written back."""

    def setUp(self):
        init(width=400, height=300)
        self.c = Circle(center=(50, 50), radius=10)
        self.addCleanup(self.c.destroy)

    def message(self, fn, *args):
        with self.assertRaises(TypeError) as cm:
            fn(*args)
        return str(cm.exception)

    def test_scratch_order_glide(self):
        msg = self.message(self.c.move_to, 1, 200, 100)
        self.assertIn("move_to(200, 100, time=1)", msg)
        self.assertNotIn("positional arguments", msg)

    def test_seconds_last(self):
        self.assertIn("move_to(200, 100, time=2)", self.message(self.c.move_to, 200, 100, 2))
        self.assertIn("move_by(10, 0, time=0.5)", self.message(self.c.move_by, 10, 0, 0.5))

    def test_turns_and_scales(self):
        self.assertIn("rotate_to(90, time=1)", self.message(self.c.rotate_to, 90, 1))
        self.assertIn("rotate_by(45, time=2)", self.message(self.c.rotate_by, 45, 2))
        self.assertIn("scale_to(2, time=1)", self.message(self.c.scale_to, 2, 1))
        self.assertIn("scale_by(0.5, time=1)", self.message(self.c.scale_by, 0.5, 1))

    def test_a_subclass_override_says_the_same(self):
        from scena import Line, Text
        ln = Line(p1=(0, 0), p2=(10, 0))
        t = Text("oi", center=(100, 100))
        self.addCleanup(ln.destroy)
        self.addCleanup(t.destroy)
        self.assertIn("rotate_to(90, time=1)", self.message(ln.rotate_to, 90, 1))
        self.assertIn("rotate_by(30, time=1)", self.message(t.rotate_by, 30, 1))
        self.assertIn("move_to(5, 5, time=1)", self.message(t.move_to, 1, 5, 5))

    def test_the_right_calls_still_work(self):
        self.c.move_to(200, 100)
        h = self.c.move_to(100, 100, time=1)
        h.cancel()
        self.c.rotate_by(10)
        self.c.scale_to(1.5)



class TestIntersectionsOfACurve(unittest.TestCase):
    """``intersections(line, track)`` listed the shapes it takes and stopped
    there; a teacher plotting y = x² as a Track could not go on (persona
    probes round 2, R2-5). The message names the route, and the route works."""

    def test_the_message_names_lines_between_spaced_points(self):
        from scena import Line, Track, intersections
        init(width=1000, height=700)
        curve = Track(points=[(100, 580), (500, 100), (900, 580)])
        level = Line(p1=(0, 280), p2=(1000, 280))
        self.addCleanup(curve.destroy)
        self.addCleanup(level.destroy)
        with self.assertRaises(TypeError) as cm:
            intersections(level, curve)
        self.assertIn("spaced_points", str(cm.exception))
        pts = curve.spaced_points(64)
        hits = []
        for a, b in zip(pts, pts[1:]):
            seg = Line(p1=a, p2=b)
            hits += intersections(level, seg)
            seg.destroy()
        self.assertEqual(len(hits), 2)


class TestForeignPoseWrites(unittest.TestCase):
    """``paddle.position = Vec2(40, 300)`` (Godot, Unity) became an own field
    nothing reads, while the read named ``.center`` (persona probes round 2,
    R2-7). The write names it too; a bare Entity keeps the name as its own."""

    def setUp(self):
        init(width=400, height=300)

    def test_a_shape_refuses_and_names_center_and_angle(self):
        from scena import Vec2
        r = Rect(center=(50, 50), width=20, height=100)
        self.addCleanup(r.destroy)
        for name, fix, value in (("position", "center", Vec2(40, 300)),
                                 ("global_position", "center", (40, 300)),
                                 ("rotation", "angle", 30), ("rotation_degrees", "angle", 30)):
            with self.subTest(name=name), self.assertRaises(AttributeError) as cm:
                setattr(r, name, value)
            self.assertIn(f"'{fix}'", str(cm.exception))

    def test_a_bare_entity_keeps_it(self):
        e = Entity()
        self.addCleanup(e.destroy)
        e.position = 3
        self.assertEqual(e.position, 3)


class TestTimerGivenACall(unittest.TestCase):
    """``every(0.6, spawn())`` ran ``spawn`` once and returned the decorator,
    silently: no wave ever came (persona probes round 2, R2-8). An explicit
    ``None`` where the function goes now raises; the decorator form (the
    function omitted) and ``on_done=`` stay."""

    def test_a_call_result_raises_naming_the_function_form(self):
        from scena import after, every, Entity
        init(width=200, height=200)
        e = Entity()
        self.addCleanup(e.destroy)
        for fn in (lambda: every(0.6, None), lambda: after(1, None),
                   lambda: e.every(0.6, None), lambda: e.after(1, None)):
            with self.assertRaises(TypeError) as cm:
                fn()
            self.assertIn("without parentheses", str(cm.exception))

    def test_the_decorator_and_keyword_forms_still_work(self):
        from scena import after, every
        init(width=200, height=200)

        @every(0.5)
        def tique():
            pass

        h = after(1, on_done=lambda: None)
        tique.handle.cancel()
        h.cancel()


class TestModeBodyCalledByHand(unittest.TestCase):
    """``self.mode = self.phase2()`` ran the body as a helper (its ``every``
    outlived the mode) and set the mode to ``None``, silently (persona probes
    round 2, R2-9). A sync mode body is entered only by the engine."""

    def test_a_direct_call_raises_and_the_mode_setter_still_enters(self):
        from scena import Rect, on_mode
        init(width=400, height=300)
        ran = []

        class Boss(Rect):
            def setup(self):
                self.mode = self.phase1

            @on_mode
            def phase1(self):
                ran.append("phase1")

            @on_mode
            def phase2(self):
                ran.append("phase2")

        b = Boss(center=(200, 150), width=40, height=20)
        self.addCleanup(b.destroy)
        self.assertEqual(ran, ["phase1"])
        with self.assertRaises(TypeError) as cm:
            b.mode = b.phase2()
        self.assertIn("self.mode = self.phase2", str(cm.exception))
        self.assertEqual(ran, ["phase1"])
        b.mode = b.phase2
        self.assertEqual(ran, ["phase1", "phase2"])
        self.assertEqual(b.mode, b.phase2)

    def test_a_plain_function_mode_still_gets_its_owner(self):
        from scena import Entity, on_mode
        init(width=400, height=300)
        got = []

        @on_mode
        def calm(e):
            got.append(e)

        @on_mode
        def idle():
            got.append("idle")

        e = Entity()
        self.addCleanup(e.destroy)
        e.mode = calm
        e.mode = idle
        self.assertEqual(got, [e, "idle"])

if __name__ == "__main__":
    unittest.main()
