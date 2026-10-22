"""Appearance links: ``@=`` on paint fields and flags (Reactive Design —
Appearance links, 2026-10-15).

``color`` / ``fill`` / ``line`` / ``line_width`` (Shape, Text), Text
``background``, Sprite ``alpha``, ``visible`` and ``flip_x`` / ``flip_y`` are
link targets: ``@=`` means ``=`` re-run whenever the formula's sources change.
Each test names the wrong implementation it exists to catch; the mutation
sweep at the bottom plants those and checks the tests fail.

    python tests/run_tiers.py focused test_paint_flag_links
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from system_support import SystemTestCase, quiet, FRAME  # noqa: E402

import scena  # noqa: E402
from scena import (  # noqa: E402
    Act, Circle, Color, Neon, Paint, Polygon, Rect, Sprite, SpriteButton, Text,
    canvas, change_act, clock, collide, st, tween, when,
)
from scena import entity as _entity  # noqa: E402
from scena.entity import Graphic, _LINKED_CHANNEL_HOSTS, _TARGET_ONLY_LINKS  # noqa: E402
from scena.state import CallableAssignError, LinkedAttributeError  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


# The appearance links each kind takes (the decision table of the plan). Any
# other kind / name pair refuses.
_SHAPE = frozenset({"color", "fill", "line", "line_width", "visible", "flip_x", "flip_y"})
_EXPECTED = {
    "Point": frozenset(), "Anchor": frozenset(),
    "Track": _SHAPE - {"visible"},
    "Text": frozenset({"color", "fill", "line", "line_width", "background", "visible"}),
    "Sprite": frozenset({"alpha", "visible", "flip_x", "flip_y"}),
    "Svg": frozenset({"alpha", "visible", "flip_x", "flip_y"}),
    "SpriteButton": frozenset({"alpha", "visible", "flip_x", "flip_y", "enabled"}),
}
_ALL_NAMES = _TARGET_ONLY_LINKS | {"enabled"}


def _graphic_kinds():
    import inspect
    for name in scena.__all__:
        kind = getattr(scena, name)
        if (inspect.isclass(kind) and issubclass(kind, Graphic)
                and not getattr(kind, "__abstractmethods__", None)):
            yield name, kind


def _rgba(paint):
    return tuple(round(float(v), 3) for v in paint.rgb)


def _png(path, w=8, h=8):
    info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    surf.getCanvas().drawPaint(skia.Paint(Color=skia.ColorWHITE))
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _screen(world):
    a = np.asarray(world.surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))
    return a[: int(canvas.height), : int(canvas.width)].astype(np.int64)


def _redder(world) -> bool:
    """The frame just drawn is more red than blue (whole screen)."""
    s = _screen(world)
    return int(s[..., 0].sum()) > int(s[..., 2].sum())


def _mid():
    return (canvas.width / 2, canvas.height / 2)


# --------------------------------------------------------------------------
# 1–4: who links, what reads, what a callable write says
# --------------------------------------------------------------------------

class TestWhoLinks(unittest.TestCase):

    def test_fixed_table_over_every_graphic_kind(self):
        """Catches: Sprite color, Point visible or Text flip becoming linkable;
        a subclass losing its bases' names (SpriteButton)."""
        seen = 0
        for name, kind in _graphic_kinds():
            want = _EXPECTED.get(name, _SHAPE)
            got = kind._scena_property_links & _ALL_NAMES
            with self.subTest(kind=name):
                self.assertEqual(got, want)
            obj = kind()
            try:
                for field in sorted(_ALL_NAMES - want):
                    with self.subTest(kind=name, refused=field):
                        with self.assertRaises((AttributeError, TypeError)):
                            obj[field] @= (lambda: st.v)
            finally:
                obj.destroy()
            seen += 1
        self.assertGreaterEqual(seen, 15, "the walk stopped reaching the kinds")

    def test_sprite_button_keeps_sprite_links(self):
        """Catches: ``getattr(cls, "_property_link_extra")`` hiding Sprite's
        names behind SpriteButton's ``{"enabled"}`` (a float anchor for visible)."""
        st.on = True
        b = SpriteButton()
        self.addCleanup(b.destroy)
        b["visible"] @= lambda: st.on
        self.assertIs(b.visible, True)
        st.on = False
        self.assertIs(b.visible, False)
        b["alpha"] @= lambda: 0.25 if st.on is False else 1.0
        self.assertAlmostEqual(b.alpha, 0.25)

    def test_reading_one_in_a_formula_follows_the_object_as_before(self):
        """Catches: source extraction made reactive by accident — an anchor no
        paint writer dirties, the sprite fast pose key turned off."""
        st.v = 1.0
        for field, make in (("visible", Circle), ("color", Circle), ("alpha", Sprite),
                            ("flip_x", Sprite), ("line_width", Rect)):
            with self.subTest(field=field):
                a = make()
                b = Rect()
                b["width"] @= (lambda a=a: 10.0 + (1.0 if getattr(a, field) else 0.0) + st.v)
                self.assertIsNone(a.__dict__.get("_field_anchors"))
                link = b["width"].owner.__dict__["_field_anchors"]["width"]._link \
                    if b.__dict__.get("_field_anchors", {}).get("width") is not None else None
                if link is not None:
                    self.assertTrue(any(src is a for src in link.sources))
                with self.assertRaises(TypeError) as cm:
                    b["color"] @= a[field]
                self.assertIn("link target only", str(cm.exception))
                b.destroy()
                a.destroy()

    def test_callable_write_points_at_the_link(self):
        """Catches: a callable falling through to ``Color(lambda)``."""
        r = Rect()
        self.addCleanup(r.destroy)
        for field in ("color", "fill", "line", "line_width", "visible", "flip_x"):
            with self.subTest(field=field):
                with self.assertRaises(CallableAssignError) as cm:
                    setattr(r, field, lambda: "red")
                self.assertIn(f"['{field}'] @= lambda", str(cm.exception))
        self.assertIsNone(r.__dict__.get("_field_anchors"))


# --------------------------------------------------------------------------
# 5, 11, 12: values
# --------------------------------------------------------------------------

class TestValues(unittest.TestCase):

    def setUp(self):
        st.n = 0
        self.r = Rect()
        self.addCleanup(self.r.destroy)

    def test_equal_color_writes_once_alpha_counts(self):
        """Catches: identity compare (a fresh ``Color`` every pull rewrites the
        paint); a compare that leaves alpha out."""
        r = self.r
        r["fill"] @= lambda: Color(1, 0, 0, 0.5 if st.n >= 10 else 1.0) if st.n >= 0 else None
        first = r.fill
        writes = []
        real = type(r)._invalidate_fill_paint
        try:
            type(r)._invalidate_fill_paint = lambda self: (writes.append(1), real(self))[1]
            st.n = 1                      # same RGBA, new Color object
            self.assertIs(r.fill, first)
            st.n = 2
            self.assertIs(r.fill, first)
            self.assertEqual(writes, [])
            st.n = 10                     # alpha only
            self.assertIsNot(r.fill, first)
            self.assertEqual(_rgba(r.fill), (1.0, 0.0, 0.0, 0.5))
        finally:
            type(r)._invalidate_fill_paint = real

    def test_a_name_every_pull_writes_once(self):
        r = self.r
        r["color"] @= lambda: "red" if st.n < 5 else "blue"
        first = r.fill
        st.n = 1
        self.assertIs(r.fill, first)
        st.n = 6
        self.assertEqual(_rgba(r.fill)[:3], (0.0, 0.0, 1.0))

    def test_line_width_clamps_like_a_formula(self):
        """Catches: the setter's ``fixed_magnitude`` on the link path (a
        negative raised mid-frame)."""
        r = self.r
        r["line_width"] @= lambda: 4.0 - st.n
        st.n = 7
        self.assertEqual(r.line_width, 0.0)
        q = Rect()
        self.addCleanup(q.destroy)
        with self.assertRaises(ValueError):
            q["line_width"] @= lambda: float("nan") + st.n
        self.assertIsNone((q.__dict__.get("_field_anchors") or {}).get("line_width"))
        self.assertEqual(q.line_width, 1.5)

    def test_a_tween_overshoot_reads_zero(self):
        """A tween tick writes through ``_write_field`` (process._tween_target):
        an elastic overshoot below zero reads 0, as a formula's does."""
        r = self.r
        r.line_width = 2.0
        h = tween(r["line_width"], 0.0, time=1.0, ease="elastic")
        self.addCleanup(h.cancel)
        r._write_field("line_width", -0.4)      # what an overshooting tick writes
        self.assertEqual(r.line_width, 0.0)

    def test_sprite_alpha_clamps(self):
        s = Sprite()
        self.addCleanup(s.destroy)
        s["alpha"] @= lambda: 1.5 + st.n
        self.assertEqual(s.alpha, 1.0)
        st.n = -3
        self.assertEqual(s.alpha, 0.0)

    def test_text_background_and_color(self):
        t = Text("hi")
        self.addCleanup(t.destroy)
        t["background"] @= lambda: (0, 0, 0, 0.5) if st.n else None
        self.assertIsNone(t.background)
        st.n = 1
        self.assertEqual(_rgba(t.background), (0.0, 0.0, 0.0, 0.5))
        t["color"] @= lambda: "red" if st.n else "white"
        t.line = "black"            # Text's color is its fill: the outline stays free
        self.assertEqual(_rgba(t.line)[:3], (0.0, 0.0, 0.0))


# --------------------------------------------------------------------------
# 7, 8: looks
# --------------------------------------------------------------------------

class TestUnderLooks(unittest.TestCase):

    def setUp(self):
        from scena import recipes as _recipes
        from scena import style as _style
        self._recipes = _recipes
        self._clock = _recipes._clock
        _recipes._clock = lambda: 0.37
        _style._RECOLOR_HIDDEN_WARNED.clear()
        warnings.simplefilter("ignore")
        st.lime = False

    def tearDown(self):
        self._recipes._clock = self._clock
        warnings.resetwarnings()

    def test_linked_color_is_color_param_under_every_look(self):
        """Catches: a link that writes the raw channels (``_fill`` / ``_line``)
        instead of ``set_color``; one that skips the look identity (then
        ``visual = None`` shows the old color)."""
        from tests.test_visual_color_param import (
            TestSetColorIsColorParam, _draw, _follower, _state)
        n = 0
        for cls, base, look in TestSetColorIsColorParam._cells():
            with self.subTest(visual=cls.__name__, **base, seeded=look._seeded()):
                st.lime = False
                ref = Circle(center=(64, 64), radius=40, color="lime")
                ref.visual = _follower(cls, base)
                got = Circle(center=(64, 64), radius=40, color="blue")
                got.visual = look
                got["color"] @= lambda: "lime" if st.lime else "blue"
                st.lime = True
                got.color                      # a read pulls, as a draw does
                self.assertLessEqual(int(np.abs(_draw(got) - _draw(ref)).max()), 2)
                got.visual = None
                self.assertEqual(_state(got), _state(Circle(radius=40, color="lime")))
                n += 1
                got.destroy()
                ref.destroy()
        self.assertGreater(n, 60, "the sweep stopped reaching the surface")

    def test_a_look_put_on_after_the_source_changed_samples_the_new_color(self):
        """Catches: a pull inside the look's apply (it skips the identity
        patch, so ``visual = None`` brings the old color back)."""
        st.lime = False
        r = Rect()
        self.addCleanup(r.destroy)
        r["color"] @= lambda: "lime" if st.lime else "red"
        r.color
        st.lime = True                       # no read before the look goes on
        r.visual = Neon()
        self.assertEqual(_rgba(r._look_identity["fill"])[:3], _rgba(Color("lime"))[:3])
        r.visual = None
        self.assertEqual(_rgba(r._fill)[:3], _rgba(Color("lime"))[:3])


# --------------------------------------------------------------------------
# 9, 10, 20: refusals change nothing; conflicts both orders
# --------------------------------------------------------------------------

def _paint_state(obj):
    d = {}
    for name in ("_fill", "_line", "_line_width", "_visual", "_background", "_alpha",
                 "_visible", "_flip_x", "_flip_y", "_enabled"):
        if hasattr(obj, name):
            v = getattr(obj, name)
            d[name] = _rgba(v) if isinstance(v, Color) else v
    ident = getattr(obj, "_look_identity", None)
    if ident is not None:
        d["ident"] = {k: (_rgba(v) if isinstance(v, Color) else v) for k, v in ident.items()}
    return d


class TestRefusals(unittest.TestCase):

    def setUp(self):
        st.v = 0.0
        warnings.simplefilter("ignore")

    def tearDown(self):
        warnings.resetwarnings()

    def _refused(self, obj, write):
        before = _paint_state(obj)
        with self.assertRaises(LinkedAttributeError):
            write()
        self.assertEqual(_paint_state(obj), before)

    def test_every_author_write_refuses_before_writing(self):
        """Catches: a refusal in an inner setter after an outer write (a Paint
        installer replaced, a look de-seeded, the fill rewritten)."""
        r = Rect(color="blue")
        self.addCleanup(r.destroy)
        r.visual = Paint("blue")
        r.visual = None
        r["fill"] @= lambda: "red" if st.v else "lime"
        for label, write in (
                ("color =", lambda: setattr(r, "color", "white")),
                ("set_color", lambda: r.set_color("white")),
                ("fill =", lambda: setattr(r, "fill", "white")),
                ("set_alpha", lambda: r.set_alpha(0.3)),
                ("visual = Paint", lambda: setattr(r, "visual", Paint("white"))),
                ("visual = Neon(seed)", lambda: setattr(r, "visual", Neon("white")))):
            with self.subTest(write=label):
                self._refused(r, write)
        q = Rect(color="blue")
        self.addCleanup(q.destroy)
        q["line"] @= lambda: "red" if st.v else "lime"
        self._refused(q, lambda: q.set_alpha(0.3))      # it rewrites fill and line
        self._refused(q, lambda: setattr(q, "color", "white"))
        q.fill = "white"                               # the fill is free
        w = Rect()
        self.addCleanup(w.destroy)
        w["line_width"] @= lambda: 2.0 + st.v
        self._refused(w, lambda: setattr(w, "line_width", 5))
        self._refused(w, lambda: setattr(w, "visual", __import__("scena").visuals.Stroke("red", width=4)))
        t = Text("x")
        self.addCleanup(t.destroy)
        t["color"] @= lambda: "red" if st.v else "white"
        t["background"] @= lambda: "red" if st.v else None
        self._refused(t, lambda: setattr(t, "color", "blue"))
        self._refused(t, lambda: t.set_color("blue"))
        self._refused(t, lambda: setattr(t, "background", "blue"))
        s = Sprite()
        self.addCleanup(s.destroy)
        for field in ("alpha", "visible", "flip_x", "flip_y"):
            s[field] @= ((lambda: 0.5 + st.v) if field == "alpha" else (lambda: st.v > 0))
        self._refused(s, lambda: setattr(s, "alpha", 0.9))
        self._refused(s, lambda: s.set_alpha(0.9))
        self._refused(s, lambda: setattr(s, "visible", False))
        self._refused(s, lambda: setattr(s, "flip_x", True))
        self._refused(s, lambda: setattr(s, "flip_y", True))

    def test_linked_enabled_refuses_a_plain_write(self):
        """Catches: ``_FlagPropertyAnchor`` without ``_writing`` / no check in
        the setter — ``b.enabled = False`` wrote silently (LK1)."""
        st.on = True
        b = SpriteButton()
        self.addCleanup(b.destroy)
        b["enabled"] @= lambda: st.on
        self._refused(b, lambda: setattr(b, "enabled", False))
        st.on = False
        self.assertIs(b.enabled, False)

    def test_paint_conflicts_both_orders(self):
        """Catches: two links on one package left to the first write."""
        for first, second in (("color", "fill"), ("fill", "color"), ("color", "line"),
                              ("line", "color")):
            with self.subTest(first=first, second=second):
                r = Rect()
                r[first] @= lambda: "red" if st.v else "blue"
                with self.assertRaises(LinkedAttributeError):
                    r[second] @= lambda: "red" if st.v else "blue"
                self.assertFalse(r._channel_linked(second))
                r.destroy()
        r = Rect()
        self.addCleanup(r.destroy)
        r["fill"] @= lambda: "red" if st.v else "blue"
        r["line"] @= lambda: "red" if st.v else "blue"      # separate channels
        t = Text("x")
        self.addCleanup(t.destroy)
        t["color"] @= lambda: "red" if st.v else "white"
        t["line"] @= lambda: "red" if st.v else "white"     # Text: color is the fill only
        with self.assertRaises(LinkedAttributeError):
            t["fill"] @= lambda: "red" if st.v else "white"

    def test_flip_conflicts_both_orders_without_a_first_write(self):
        """Catches: relying on the flip's first write (a sprite at 90° flips
        its heading onto itself), and refusing a pivot point."""
        s = Sprite()
        self.addCleanup(s.destroy)
        s.angle = 90                     # flip_x maps 90 → 90: no write to fail
        s["angle"] @= lambda: 90.0 + st.v * 0
        with self.assertRaises(LinkedAttributeError):
            s["flip_x"] @= lambda: st.v > 0
        s2 = Sprite()
        self.addCleanup(s2.destroy)
        s2["flip_x"] @= lambda: st.v > 0
        with self.assertRaises(LinkedAttributeError):
            s2["angle"] @= lambda: st.v
        other = Sprite()
        self.addCleanup(other.destroy)
        with self.assertRaises(LinkedAttributeError):
            s2 @= other                  # the whole object drives the pose
        p = Polygon(points=[(0, 0), (10, 0), (0, 10)])
        self.addCleanup(p.destroy)
        p._mirror_points()[1] @= (lambda: (10.0 + st.v, 0.0))
        with self.assertRaises(LinkedAttributeError):
            p["flip_x"] @= lambda: st.v > 0
        q = Polygon(points=[(0, 0), (10, 0), (0, 10)])
        self.addCleanup(q.destroy)
        q["flip_y"] @= lambda: st.v > 0
        with self.assertRaises(LinkedAttributeError):
            q._mirror_points()[2] @= (lambda: (0.0, 10.0 + st.v))
        r = Rect(center=lambda: (st.v * 10, 0.0), width=10, height=5)
        self.addCleanup(r.destroy)
        r["flip_x"] @= lambda: st.v > 0            # the center is the pivot
        st.v = 1.0
        self.assertIs(r.flip_x, True)


# --------------------------------------------------------------------------
# 13, 14, 15: copy verbs, clone, destroy
# --------------------------------------------------------------------------

class TestCopies(unittest.TestCase):

    def setUp(self):
        st.red = False
        warnings.simplefilter("ignore")

    def tearDown(self):
        warnings.resetwarnings()

    def test_restore_visual_and_look_like_keep_the_formula(self):
        """Catches: a copy verb writing over a linked field."""
        r = Rect(color="white")
        self.addCleanup(r.destroy)
        r["color"] @= lambda: "red" if st.red else "blue"
        r.save_visual()
        st.red = True
        r.restore_visual()
        self.assertEqual(_rgba(r._fill)[:3], (1.0, 0.0, 0.0))
        donor = Rect(color="lime")
        self.addCleanup(donor.destroy)
        r.look_like(donor)
        self.assertEqual(_rgba(r._fill)[:3], (1.0, 0.0, 0.0))
        s = Sprite()
        self.addCleanup(s.destroy)
        s["alpha"] @= lambda: 0.25 if st.red else 0.75
        s.save_visual()
        st.red = False
        s.restore_visual()
        self.assertAlmostEqual(s._alpha, 0.75)
        s.look_like(Sprite())
        self.assertAlmostEqual(s._alpha, 0.75)

    def test_clone_takes_this_frames_value_and_no_link(self):
        """Catches: the copy snapshotting the last pulled value."""
        r = Rect()
        self.addCleanup(r.destroy)
        r["color"] @= lambda: "red" if st.red else "blue"
        r["visible"] @= lambda: not st.red
        r.color
        st.red = True                       # no read, no draw
        c = r.clone()
        self.addCleanup(c.destroy)
        self.assertEqual(_rgba(c._fill)[:3], (1.0, 0.0, 0.0))
        self.assertIs(c._visible, False)
        self.assertFalse(c._channel_linked("color"))
        c.color = "lime"                    # the copy is free
        s = Sprite()
        self.addCleanup(s.destroy)
        s["flip_x"] @= lambda: st.red
        st.red = False
        s.flip_x
        st.red = True
        k = s.clone()
        self.addCleanup(k.destroy)
        self.assertIs(k._flip_x, True)

    def test_destroy_stops_the_formula(self):
        """L3: a destroyed object's formula never runs again."""
        calls = []
        r = Rect()
        r["color"] @= lambda: (calls.append(1), "red" if st.red else "blue")[1]
        self.assertIn(r, _LINKED_CHANNEL_HOSTS)
        r.destroy()
        n = len(calls)
        st.red = not st.red
        _entity.refresh_linked_channels()
        _entity.refresh_linked_visible()
        self.assertEqual(len(calls), n)
        self.assertNotIn(r, _LINKED_CHANNEL_HOSTS)


# --------------------------------------------------------------------------
# Frames: 6, 15 (act), 16–19, 21, 22
# --------------------------------------------------------------------------

class TestFrames(SystemTestCase, unittest.TestCase):

    def setUp(self):
        super().setUp()
        st.blue = False
        st.show = False
        warnings.simplefilter("ignore")
        self.addCleanup(warnings.resetwarnings)
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.png = os.path.join(self._dir.name, "white.png")
        _png(self.png)

    def _first_drawn_frame(self, writer, check, frames=6):
        """Step until ``writer`` ran; return (frame it wrote, frame drawn new)."""
        wrote = {}

        def write():
            wrote.setdefault("frame", self.w.frames_run)
        writer(write)
        for _ in range(frames):
            self.w.step(1, draw=True)
            if "frame" in wrote and check():
                return wrote["frame"], self.w.frames_run - 1
        return wrote.get("frame"), None

    def _blue_when(self, at):
        def writer(mark):
            def upd(dt):
                if self.w.frames_run == at:
                    st.blue = True
                    mark()
            self.w.on_update(upd)
        return writer

    def test_same_frame_draw_plain_look_batch_text_sprite(self):
        """Catches: a pull inside individual draw paths (the look batch groups
        by look first; Text has no draw of its own) and the ``_blit_plain``
        read before its pull."""
        mid = _mid()
        cases = {}
        r = self.track(Rect(center=mid, width=4000, height=4000))
        r["color"] @= lambda: "blue" if st.blue else "red"
        cases["plain"] = (r, lambda: not _redder(self.w))
        for case, check in self._cases(mid):
            cases[case] = check
        for case, (obj, check) in cases.items():
            with self.subTest(path=case):
                for o, _c in cases.values():
                    o.visible = (o is obj) if not o._channel_linked("visible") else o.visible
                st.blue = False
                self.w.step(2, draw=True)
                self.assertFalse(check(), "the starting frame already shows the change")
                start = self.w.frames_run
                wrote, drawn = self._first_drawn_frame(self._blue_when(start), check)
                self.w.on_update(None)
                self.assertEqual(drawn, wrote, f"{case}: drawn a frame late")

    def _cases(self, mid):
        canvas.batch_shared_filters = True
        a = self.track(Rect(center=(mid[0] - 60, mid[1]), width=80, height=80))
        b = self.track(Rect(center=(mid[0] + 60, mid[1]), width=80, height=80))
        for x in (a, b):
            x.visual = Neon()
            x["color"] @= lambda: "blue" if st.blue else "red"
        yield "look batch", (a, lambda: not _redder(self.w))
        t = self.track(Text("████", center=mid, font_size=120))
        t["background"] @= lambda: (0, 0, 1, 1) if st.blue else (1, 0, 0, 1)
        t["color"] @= lambda: (0, 0, 1, 1) if st.blue else (1, 0, 0, 1)
        yield "text", (t, lambda: not _redder(self.w))
        s = self.track(Sprite(self.png, center=mid, width=4000, height=4000))
        s["alpha"] @= lambda: 0.1 if st.blue else 1.0
        yield "sprite blit", (s, lambda: _screen(self.w)[..., 1].mean() < 100)

    def _source_written_in(self, place):
        """A writer that sets ``st.blue`` from ``place`` once the world runs."""
        mid = _mid()
        if place == "update":
            return self._blue_when(self.w.frames_run + 1)
        if place == "collide":
            self.track(Circle(center=(mid[0] + 9000, mid[1]), radius=5, group="pa"))
            mover = self.track(Circle(center=(mid[0] + 9000, mid[1] + 50), radius=5, group="pb"))

            def writer(mark):
                @collide("pa", "pb")
                def _hit(a, b_, info):
                    st.blue = True
                    mark()
                go = self.w.frames_run + 2
                self.w.on_update(lambda dt: mover.move_to(mid[0] + 9000, mid[1])
                                 if self.w.frames_run == go else None)
            return writer
        if place == "when":
            def writer(mark):
                st.go = False

                @when(lambda: clock.frame >= 0 and st.go)
                def _go():
                    st.blue = True
                    mark()
                go = self.w.frames_run + 2
                self.w.on_update(lambda dt: setattr(st, "go", True)
                                 if self.w.frames_run == go else None)
            return writer
        if place == "pre-draw on_done":
            other = self.track(Circle(center=(mid[0] + 9000, mid[1]), radius=5))

            def writer(mark):
                def done(_s):
                    st.blue = True
                    mark()
                other.flash(duration=3 * FRAME, on_done=done)
            return writer
        raise AssertionError(place)

    def test_written_anywhere_in_the_frame_is_drawn_that_frame(self):
        """Catches: a refresh only at hover (misses flush / @when / pre-draw
        writes) or only in update."""
        mid = _mid()
        r = self.track(Rect(center=mid, width=4000, height=4000))
        r["color"] @= lambda: "blue" if st.blue else "red"
        for place in ("update", "collide", "when", "pre-draw on_done"):
            with self.subTest(written_in=place):
                st.blue = False
                self.w.on_update(None)
                self.w.step(1, draw=True)
                self.assertTrue(_redder(self.w))
                wrote, drawn = self._first_drawn_frame(self._source_written_in(place),
                                                       lambda: not _redder(self.w), frames=12)
                self.assertIsNotNone(wrote, f"{place}: the writer never ran")
                self.assertEqual(drawn, wrote, f"{place}: drawn a frame late")
                scena.reset_collisions() if hasattr(scena, "reset_collisions") else None

    def test_hover_sees_visible_written_this_frame(self):
        """Catches: ``visible`` refreshed only before the draw (hover runs
        first) or only at the start of collision (a handler's write)."""
        mid = _mid()
        hovered = []
        r = self.track(Rect(center=mid, width=200, height=200))
        r.on_hover = lambda me: hovered.append(self.w.frames_run)
        r["visible"] @= lambda: st.show
        self.w.fw.shape_manager.note_pointer(world_xy=mid)
        self.w.step(2)
        self.assertEqual(hovered, [])
        at = self.w.frames_run + 1

        def upd(dt):
            if self.w.frames_run == at:
                st.show = True
        self.w.on_update(upd)
        self.w.step(3)
        self.assertEqual(hovered[:1], [at])
        # In a collision handler.
        self.w.on_update(None)
        st.show = False
        self.w.step(2)
        hovered.clear()
        self.track(Circle(center=(mid[0] + 9000, mid[1]), radius=5, group="ha"))
        mover = self.track(Circle(center=(mid[0] + 9000, mid[1] + 50), radius=5, group="hb"))
        hit = {}

        @collide("ha", "hb")
        def _hit(a, b, info):
            st.show = True
            hit.setdefault("frame", self.w.frames_run)
        go = self.w.frames_run + 1
        self.w.on_update(lambda dt: mover.move_to(mid[0] + 9000, mid[1])
                         if self.w.frames_run == go else None)
        self.w.step(3)
        self.assertEqual(hovered[:1], [hit.get("frame")])

    def test_park_and_resume_follow_the_formula(self):
        """Catches: resume writing a stale stash; a compare against the getter
        (a parked ``visible`` reads False)."""
        r = self.track(Rect())
        st.show = True
        r["visible"] @= lambda: st.show
        r.active = False
        self.assertIs(r._visible, False)
        st.show = False
        r.visible                        # a read while parked pulls into the stash
        r.active = True
        self.assertIs(r._visible, False)
        r.active = False
        st.show = True
        self.w.step(1)
        r.active = True
        self.assertIs(r._visible, True)

    def test_parked_formula_is_not_run_until_resume(self):
        """L4: the refreshes skip a parked host."""
        calls = []
        r = self.track(Rect())
        r["color"] @= lambda: (calls.append(1), "blue" if st.blue else "red")[1]
        r.active = False
        n = len(calls)
        st.blue = True
        self.w.step(3, draw=True)
        self.assertEqual(len(calls), n)
        r.active = True
        self.w.step(1, draw=True)            # the next draw takes the formula's value
        self.assertEqual(_rgba(r._fill)[:3], (0.0, 0.0, 1.0))
        self.assertEqual(len(calls), n + 1)

    def test_fades_refuse_a_linked_visible_at_the_call(self):
        """Catches: the refusal left to ``finish`` (it swallows errors: the
        shape popped back shown with no word)."""
        r = self.track(Rect())
        r["visible"] @= lambda: not st.blue
        for verb in ("fade_out", "fade_in", "dissolve_out", "dissolve_in", "implode"):
            with self.subTest(verb=verb):
                before = (r._visible, getattr(getattr(r, "_tx_state", None), "life", None))
                with self.assertRaises(LinkedAttributeError):
                    getattr(r, verb)()
                self.assertEqual((r._visible, getattr(getattr(r, "_tx_state", None), "life", None)),
                                 before)
        q = self.track(Rect())
        q.fade_out(duration=1.0)
        with self.assertRaises(LinkedAttributeError):
            q["visible"] @= lambda: st.show
        self.assertFalse(q._channel_linked("visible"))

    def test_flip_reaches_collision_the_frame_it_changes(self):
        """Catches: flip missing from the pose pull (collision saw last
        frame's mirror)."""
        mid = _mid()
        tri = self.track(Polygon(points=[(mid[0], mid[1]), (mid[0] + 100, mid[1]),
                                         (mid[0], mid[1] + 100)], group="tri"))
        # Only the mirrored triangle (about its center) covers this point:
        # the original has nothing left of its first vertex.
        probe_xy = (mid[0] - 20, mid[1] + 5)
        self.track(Circle(center=probe_xy, radius=2, group="dot"))
        st.flip = False
        tri["flip_x"] @= lambda: st.flip
        self.assertFalse(tri.contains_point(probe_xy))
        hit = []

        @collide("tri", "dot")
        def _hit(a, b, info):
            hit.append(self.w.frames_run)
        self.w.step(2)
        self.assertEqual(hit, [])
        at = self.w.frames_run
        self.w.on_update(lambda dt: setattr(st, "flip", True) if self.w.frames_run == at else None)
        self.w.step(2)
        self.assertEqual(hit[:1], [at])
        self.assertTrue(tri.contains_point(probe_xy))

    def test_act_link_on_a_game_object_is_undone_with_the_act(self):
        """An act's link on a game object leaves with the act (PA1), and the
        color it had comes back through the setter."""
        r = Rect(color="blue")

        class Stage(Act):
            def setup(self):
                self.src = Circle(radius=10)
                r["color"] @= lambda: "red" if self.src.radius > 5 else "lime"

        class Next(Act):
            pass

        self.w.begin_game(Stage)
        self.assertEqual(_rgba(r.color)[:3], (1.0, 0.0, 0.0))
        with quiet():
            change_act(Next)
        self.assertFalse(r._channel_linked("color"))
        self.assertEqual(_rgba(r.color)[:3], (0.0, 0.0, 1.0))
        r.color = "lime"
        r.destroy()

    def test_unlinked_objects_stay_on_the_fast_paths(self):
        """Catches, by structure: a paint / flag write that makes an anchor (the
        sprite fast pose key, ``_plain_blit``)."""
        from scena.collision import _sprite_pose_key_fast
        r = self.track(Rect())
        s = self.track(Sprite(self.png, width=20, height=20))
        r.color = "red"
        r.fill = "blue"
        r.line_width = 3
        r.visible = False
        r.visible = True
        r.flip_x = True
        s.alpha = 0.5
        s.flip_x = True
        s.visible = True
        self.w.step(2, draw=True)
        for obj in (r, s):
            self.assertIsNone(obj.__dict__.get("_field_anchors"))
            self.assertNotIn(obj, _LINKED_CHANNEL_HOSTS)
        self.assertTrue(s._plain_blit)
        self.assertIsNotNone(_sprite_pose_key_fast(s))


class TestLinkDoors(unittest.TestCase):
    """The value rules a link applies (Scena Design — Numbers): what ``=``
    refuses, a link refuses at ``@=`` and installs nothing (W3)."""

    def test_bad_values_refuse_and_link_nothing(self):
        st.k = 1.0
        for field, bad, make, err in (
                ("line_width", "x", Rect, TypeError), ("line_width", True, Rect, TypeError),
                ("visible", "no", Rect, TypeError), ("flip_x", 2, Sprite, TypeError),
                ("alpha", float("inf"), Sprite, ValueError), ("color", Neon(), Rect, TypeError)):
            with self.subTest(field=field, bad=bad):
                o = make()
                with self.assertRaises(err):
                    o[field] @= (lambda b=bad: b if st.k else b)
                self.assertFalse(o._channel_linked(field))
                self.assertIsNone((o.__dict__.get("_field_anchors") or {}).get(field))
                o.destroy()

    def test_shared_material_is_not_mutated(self):
        """A material a formula hands to two shapes stays the author's object
        (HP1: a write gives the writer a new object)."""
        from scena import Gradient
        st.k = 1.0
        g = Gradient("plasma")
        stops = [_rgba(c) for c in g._colors]
        a, b = Rect(), Rect()
        for r in (a, b):
            r["fill"] @= lambda: g if st.k else None
            self.addCleanup(r.destroy)
        a.visual = Neon()
        a.visual = None
        self.assertIs(a.fill, g)
        self.assertIs(b.fill, g)
        self.assertEqual([_rgba(c) for c in g._colors], stops)

    def test_linked_flip_composes_with_a_timed_rotate(self):
        """A flip formula writes the flip, as ``flip_x =`` does: a timed turn
        running meanwhile composes the same way (only a formula is exclusive)."""
        st.f = False
        linked, manual = Sprite(), Sprite()
        self.addCleanup(linked.destroy)
        self.addCleanup(manual.destroy)
        linked["flip_x"] @= lambda: st.f
        linked.rotate_by(90, time=1.0)
        manual.rotate_by(90, time=1.0)
        st.f = True
        linked.flip_x
        manual.flip_x = True
        self.assertEqual(linked.angle, manual.angle)
        self.assertEqual(linked.flip_x, manual.flip_x)


class TestConstructorFormulas(unittest.TestCase):

    def test_constructor_functions_link(self):
        st.k = 1.0
        r = Rect(color=lambda: "red" if st.k > 0 else "blue", line_width=lambda: st.k * 3)
        self.addCleanup(r.destroy)
        t = Text("x", color=lambda: "red" if st.k > 0 else "white",
                 background=lambda: (0, 0, 0, 1) if st.k > 0 else None)
        self.addCleanup(t.destroy)
        s = Sprite(flip_x=lambda: st.k < 0)
        self.addCleanup(s.destroy)
        self.assertEqual(r.line_width, 3.0)
        self.assertIsNotNone(t.background)
        self.assertIs(s.flip_x, False)
        st.k = -1.0
        self.assertEqual(_rgba(r.color)[:3], (0.0, 0.0, 1.0))
        self.assertEqual(r.line_width, 0.0)
        self.assertIsNone(t.background)
        self.assertIs(s.flip_x, True)
        self.assertTrue(r._channel_linked("color"))


class TestPlainValueRefuses(unittest.TestCase):
    """A2 (RA 0.9.0): ``lamp["visible"] @= box.checked`` (a bool since
    0.9.0), ``sprite["alpha"] @= 0.5`` and every property-backed field given
    a number took it in once (``_assign_formula`` copied a Number) and linked
    nothing, while ``c["radius"] @= 5`` refused; a color channel given a
    number said "Cannot make a Color". Every graphic kind × every name it
    links (appearance channels, heading, scale) × a constant, a value read
    from a cell and a bool: the @= words, nothing linked, the value kept."""

    _CONSTANT = {"color": "red", "fill": "blue", "line": "red", "background": "red",
                 "line_width": 3, "alpha": 0.5, "angle": 30, "scale": 2}

    def test_every_linked_name_refuses_a_plain_value(self):
        st.a2_on = True
        st.a2_num = 0.25
        seen = 0
        for name, kind in _graphic_kinds():
            obj = kind()
            try:
                for field in sorted(kind._scena_property_links | {"angle", "scale"}):
                    try:
                        obj[field]
                    except (AttributeError, TypeError):
                        continue            # not a field of this kind
                    for label, value in (("constant", self._CONSTANT.get(field, True)),
                                         ("cell read", st.a2_num), ("bool", st.a2_on),
                                         ("int", 1)):
                        with self.subTest(kind=name, field=field, value=label):
                            before = getattr(obj, field)
                            with self.assertRaises((TypeError, AttributeError)) as cm:
                                obj[field] @= value
                            if field in kind._scena_property_links:
                                self.assertIn("@= needs a linkable object", str(cm.exception))
                            self.assertFalse(obj[field].is_linked)
                            self.assertEqual(getattr(obj, field), before)
                            seen += 1
            finally:
                obj.destroy()
        self.assertGreater(seen, 300, "the walk stopped reaching the channels")

    def test_a_cell_handle_and_a_function_still_link(self):
        from scena import CheckBox
        box = CheckBox()
        self.addCleanup(box.destroy)
        lamp = Circle()
        self.addCleanup(lamp.destroy)
        lamp["visible"] @= box["checked"]
        self.assertTrue(lamp["visible"].is_linked)
        box.checked = True
        self.assertIs(lamp.visible, True)
        box.checked = False
        self.assertIs(lamp.visible, False)
        s = Sprite()
        self.addCleanup(s.destroy)
        s["alpha"] @= lambda: 0.5 if box.checked else 1.0
        self.assertAlmostEqual(s.alpha, 1.0)
        box.checked = True
        self.assertAlmostEqual(s.alpha, 0.5)


class TestFlagRefusalNamesAWorkingFix(unittest.TestCase):
    """B7 (RA 0.9.0): ``Text("t")["flip_x"] @= …`` said "Set it with
    ``text.flip_x = …``", and ``text.flip_x = True`` raises (Text cannot
    flip). Class guard: on every graphic kind, a flag whose @= refuses with
    "set it with ``=``" takes ``= True``; one whose ``= True`` raises gives
    the link the same reason."""

    def test_every_refused_flag_names_a_fix_that_works(self):
        seen = 0
        for name, kind in _graphic_kinds():
            for field in ("flip_x", "flip_y", "visible"):
                if field in kind._scena_property_links:
                    continue
                obj = kind()
                try:
                    try:
                        obj[field] @= (lambda: st.v)
                    except (AttributeError, TypeError) as e:
                        link_msg = str(e)
                    else:                       # pragma: no cover - a link where none is due
                        self.fail(f"{name}[{field!r}] linked")
                    try:
                        setattr(obj, field, True)
                    except (AttributeError, TypeError) as e:
                        set_msg = str(e)
                    else:
                        set_msg = None
                    with self.subTest(kind=name, field=field):
                        if set_msg is None:
                            continue
                        self.assertNotIn("Set it with", link_msg)
                        self.assertIn("cannot be flipped" if field.startswith("flip")
                                      else field, link_msg)
                        seen += 1
                finally:
                    obj.destroy()
        self.assertGreaterEqual(seen, 2, "Text's flips stopped reaching the check")

    def test_text_flip_link_says_turn_it(self):
        t = Text("t")
        self.addCleanup(t.destroy)
        for axis in ("x", "y"):
            with self.assertRaises(AttributeError) as cm:
                t[f"flip_{axis}"] @= (lambda: st.v)
            msg = str(cm.exception)
            self.assertIn(f"Text.flip_{axis} cannot be linked", msg)
            self.assertIn('text["angle"] @= lambda:', msg)


class TestLinkWriteFastPath(unittest.TestCase):
    """The link's own write passes the setters' refusal on the host's
    ``_alink_writing`` flag (Reactive Design — Appearance links, Cost): one
    dict read, not a walk of the host's anchors per setter (a ``color`` write
    meets three: set_color, fill, line). Behaviour is ``=``'s."""

    def setUp(self):
        st.t = 0.0
        warnings.simplefilter("ignore")
        self.addCleanup(warnings.resetwarnings)

    def _track(self, obj):
        self.addCleanup(obj.destroy)
        return obj

    def test_the_link_write_takes_the_flag_not_the_anchor_walk(self):
        """Catches: the slow path back (the refusal walks the anchors on the
        link's own write) in either layer, style's or entity's."""
        r = self._track(Rect())
        r["color"] @= lambda: Color(st.t, 0.2, 0.4)
        r["visible"] @= lambda: st.t < 0.8
        r.fill, r.visible

        class Counting(dict):
            walks = 0

            def values(self):
                Counting.walks += 1
                return super().values()

        r.__dict__["_field_anchors"] = Counting(r.__dict__["_field_anchors"])
        calls = []
        real = _entity._refuse_linked_channel

        def spy(obj, names, operation):
            calls.append(names)
            return real(obj, names, operation)

        from scena import shapes as _shapes     # Shape.visible's own binding
        _entity._refuse_linked_channel = _shapes._refuse_linked_channel = spy
        try:
            for t in (0.1, 0.5, 0.9):
                st.t = t
                fill = r.fill
                self.assertEqual(_rgba(fill)[0], round(t, 3))
                self.assertIs(r.visible, t < 0.8)
            self.assertEqual(calls, [("visible",)])     # set_color passes in style
            self.assertEqual(Counting.walks, 0)
            # The author's write still refuses, before writing.
            with self.assertRaises(LinkedAttributeError):
                r.color = "red"
            with self.assertRaises(LinkedAttributeError):
                r.visible = True
            self.assertEqual(_rgba(r.fill)[0], 0.9)
        finally:
            _entity._refuse_linked_channel = _shapes._refuse_linked_channel = real
        self.assertFalse(r.__dict__.get("_alink_writing"))

    def test_lands_where_the_hand_write_lands(self):
        """``@=`` is ``=`` re-run: same paint, same look identity, same number
        of paint writes (the look revision the cull cache keys on)."""
        from scena import Colormap
        cmap = Colormap.from_colors("cyan", "medium purple", "hot pink", "orange")
        for look in (None, Neon):
            a = self._track(Circle(center=(10, 10), radius=4))
            b = self._track(Circle(center=(10, 10), radius=4))
            if look is not None:
                a.visual = look()
                b.visual = look()
            a["color"] @= lambda: cmap.get_color(st.t)
            a.fill
            b.color = cmap.get_color(st.t)
            last = st.t
            for t in (0.3, 0.3, 0.7, 1.0, 0.25):
                st.t = t
                rev_a = a.__dict__.get("_look_rev", 0)
                rev_b = b.__dict__.get("_look_rev", 0)
                a.fill
                b.color = cmap.get_color(t)
                with self.subTest(look=look, t=t):
                    self.assertEqual(_paint_state(a), _paint_state(b))
                    self.assertEqual(_rgba(a.color), _rgba(b.color))
                    if t != last:   # a repeat: the link compares with its last write
                        self.assertEqual(a.__dict__.get("_look_rev", 0) - rev_a,
                                         b.__dict__.get("_look_rev", 0) - rev_b)
                last = t
            self.assertFalse(a.__dict__.get("_alink_writing"))

    def test_a_result_of_the_fields_class_skips_the_doors(self):
        """A ``Color`` result for a paint field and a ``bool`` for a flag are
        what ``_normalize`` would return: they skip it. A name, an int flag
        and every amount take it."""
        from scena.state import _AmountChannelAnchor, _FlagChannelAnchor, _PaintChannelAnchor
        r = self._track(Rect())
        st.v = 0
        r["color"] @= lambda: Color(0.1 * st.v, 0, 0) if st.v < 5 else "blue"
        r["visible"] @= lambda: (st.v % 2 == 0) if st.v < 5 else st.v % 2
        r["line_width"] @= lambda: st.v - 3
        r.fill, r.visible, r.line_width
        seen = []
        patched = []
        for kind in (_PaintChannelAnchor, _FlagChannelAnchor, _AmountChannelAnchor):
            real = kind.__dict__["_normalize"]

            def spy(self, value, real=real):
                seen.append(self._scalar_name)
                return real(self, value)
            kind._normalize = spy
            patched.append((kind, real))
        try:
            st.v = 1
            r.fill, r.visible, r.line_width
            self.assertEqual(sorted(seen), ["line_width"])
            self.assertEqual(r.line_width, 0.0)         # clamps as a formula does
            seen.clear()
            st.v = 7
            r.fill, r.visible, r.line_width
            self.assertEqual(sorted(seen), ["color", "line_width", "visible"])
            self.assertIs(r.visible, True)              # 1 reads as a flag
            self.assertEqual(_rgba(r.fill), (0.0, 0.0, 1.0, 1.0))
        finally:
            for kind, real in patched:
                kind._normalize = real

    def test_the_flag_is_given_back(self):
        """Catches: a flag left set after a write that raised (every later
        author write would pass the refusal), and a nested link write on the
        same host that clears the outer write's flag."""
        r = self._track(Rect())
        r["color"] @= lambda: Color(st.t, 0.0, 0.0)
        r["visible"] @= lambda: st.t < 0.5
        r.fill, r.visible
        seen = []
        real = type(r)._invalidate_fill_paint

        def nested(self):
            self.visible                    # pulls the dirty visible link
            seen.append(self.__dict__.get("_alink_writing"))
            return real(self)

        type(r)._invalidate_fill_paint = nested
        try:
            st.t = 0.6
            r.fill
        finally:
            type(r)._invalidate_fill_paint = real
        self.assertEqual(seen, [True])
        self.assertIs(r.visible, False)
        self.assertFalse(r.__dict__.get("_alink_writing"))

        def boom(self, *a):
            raise RuntimeError("boom")

        real_set = type(r).set_color
        type(r).set_color = boom
        try:
            st.t = 0.2
            with self.assertRaises(RuntimeError):
                r.fill
        finally:
            type(r).set_color = real_set
        self.assertFalse(r.__dict__.get("_alink_writing"))
        with self.assertRaises(LinkedAttributeError):
            r.color = "red"
        with self.assertRaises(LinkedAttributeError):
            r.fill = "red"
        self.assertEqual(_rgba(r.fill)[0], 0.2)     # the retry writes


# --------------------------------------------------------------------------
# Canaries: each test above catches the wrong implementation it names
# --------------------------------------------------------------------------

_M = "test_paint_flag_links."


def _plant_raw_color(self, new_value):
    """A color link that writes the raw fill (skips set_color / the identity)."""
    from scena.state import _ChannelAnchor
    if self._scalar_name != "color":
        return _ChannelAnchor._takein_impl(self, new_value)
    parent = self._scalar_parent
    value = self._normalize(new_value)
    object.__setattr__(parent, "_fill", value)
    parent._invalidate_fill_paint()
    return True


def _plant_pull_inside_apply(obj, names):
    """No pull when a look goes on (the whole set) and getters pull mid-apply."""
    if len(names) > 3:
        return
    anchors = obj.__dict__.get("_field_anchors") or {}
    for name in names:
        a = anchors.get(name)
        if a is not None and a._link is not None:
            a._ensure_fresh()


def _plant_refuse_in_channels_only(obj, names, operation):
    """The refusal only in the fill / line setters (after outer writes)."""
    if operation in ("set fill on", "set line on"):
        from scena.entity import _refuse_linked_channel
        _refuse_linked_channel(obj, names, operation)


def _plant_refresh_parked(*a, **k):
    """The draw-head refresh without the parked skip (L4)."""
    from scena.state import _pull_channel_links
    for host in list(_LINKED_CHANNEL_HOSTS):
        if not getattr(host, "_destroyed", False):
            _pull_channel_links(host, type(host)._scena_target_only)


def _plant_flip_anchor_on_write(kind):
    """A plain flip write that makes an anchor (``obj.x = v`` goes through the
    class route table, so the plant wraps the method the setter calls)."""
    real = kind._apply_flip

    def apply(self, axis, value, *, force=False):
        self._ensure_scalar_anchor(f"flip_{axis}")
        return real(self, axis, value, force=force)
    return apply


def _plant_ignore_flag(real_name, module):
    """The refusal as it was before the flag: it walks the host's anchors on
    the link's own write."""
    real = getattr(sys.modules[module], real_name)

    def refuse(obj, names, operation):
        d = obj.__dict__
        was = d.pop("_alink_writing", False)
        try:
            return real(obj, names, operation)
        finally:
            d["_alink_writing"] = was
    return refuse


def _plant_flag_kept(kind, value):
    """A channel write that leaves ``_alink_writing`` at ``value`` after it."""
    real = kind._takein_impl

    def takein(self, new_value):
        try:
            return real(self, new_value)
        finally:
            self._scalar_parent.__dict__["_alink_writing"] = value
    return takein


class TestCanaries(unittest.TestCase):
    """The mutation sweep, kept: a planted wrong implementation makes its test
    fail (gate tier; ``SCENA_CANARIES=0`` skips)."""

    def _catch(self, test, patches, what):
        import diff_support
        diff_support.assert_catches(self, _M + test, patches, what)

    def test_mro_getattr_hides_sprite_links(self):
        hidden = frozenset({"angle", "scale", "enabled"})
        self._catch("TestWhoLinks.test_sprite_button_keeps_sprite_links",
                    [(SpriteButton, "_scena_property_links", hidden),
                     (SpriteButton, "_scena_target_only", frozenset())],
                    "a subclass's _property_link_extra hiding its bases'")
        self._catch("TestWhoLinks.test_fixed_table_over_every_graphic_kind",
                    [(SpriteButton, "_scena_property_links", hidden)],
                    "a link table that loses Sprite's names")

    def test_sources_made_reactive(self):
        self._catch("TestWhoLinks.test_reading_one_in_a_formula_follows_the_object_as_before",
                    [(k, "_scena_target_only", frozenset()) for k in (Circle, Sprite, Rect)],
                    "appearance fields read as formula sources")

    def test_identity_compare(self):
        from scena.state import _PaintChannelAnchor
        self._catch("TestValues.test_equal_color_writes_once_alpha_counts",
                    [(_PaintChannelAnchor, "_same", lambda self, a, b: a is b)],
                    "a Color compared by identity")
        self._catch("TestValues.test_equal_color_writes_once_alpha_counts",
                    [(_PaintChannelAnchor, "_same",
                      lambda self, a, b: a is b or (isinstance(a, Color) and isinstance(b, Color)
                                                    and a.rgb[:3] == b.rgb[:3]))],
                    "a compare that leaves alpha out")

    def test_no_draw_head_refresh(self):
        noop = lambda *a, **k: None  # noqa: E731
        self._catch("TestFrames.test_same_frame_draw_plain_look_batch_text_sprite",
                    [("scena.orchestration", "refresh_linked_channels", noop)],
                    "links pulled only where a draw path reads them")
        self._catch("TestFrames.test_written_anywhere_in_the_frame_is_drawn_that_frame",
                    [("scena.orchestration", "refresh_linked_channels", noop)],
                    "no refresh before the draw")

    def test_raw_channel_write(self):
        from scena.state import _PaintChannelAnchor
        self._catch("TestUnderLooks.test_linked_color_is_color_param_under_every_look",
                    [(_PaintChannelAnchor, "_takein_impl", _plant_raw_color)],
                    "a color link that writes the raw fill")

    def test_pull_inside_look_apply(self):
        self._catch("TestUnderLooks.test_a_look_put_on_after_the_source_changed_samples_the_new_color",
                    [("scena.style", "_pull_channel_links", _plant_pull_inside_apply)],
                    "a link pulled inside a look's apply")

    def test_refusal_after_outer_writes(self):
        self._catch("TestRefusals.test_every_author_write_refuses_before_writing",
                    [("scena.style", "_refuse_linked_paint", _plant_refuse_in_channels_only)],
                    "a refusal only in the inner fill / line setters")

    def test_flip_conflicts_left_to_the_first_write(self):
        self._catch("TestRefusals.test_flip_conflicts_both_orders_without_a_first_write",
                    [(Graphic, "_refuse_flip_link_conflict", lambda self, name: None)],
                    "flip link conflicts left to the flip's first write")
        self._catch("TestRefusals.test_flip_conflicts_both_orders_without_a_first_write",
                    [("scena.shapes", "_near_pivot", lambda *a: False)],
                    "a flip refusing the pivot point it does not move")

    def test_clone_without_pull(self):
        # ``look_like`` (the copy's paint) pulls the source too: a clone that
        # snapshots stale values has neither pull.
        no_pull = lambda obj, names: None  # noqa: E731
        self._catch("TestCopies.test_clone_takes_this_frames_value_and_no_link",
                    [("scena.state", "_pull_channel_links", no_pull),
                     ("scena.style", "_pull_channel_links", no_pull),
                     (Graphic, "_pull_property_anchors", lambda self: None)],
                    "a clone that snapshots the last pulled value")

    def test_resume_without_the_formula(self):
        self._catch("TestFrames.test_park_and_resume_follow_the_formula",
                    [("scena.state", "_reapply_channel_links", lambda obj: None)],
                    "a resume that does not re-apply a linked visible")

    def test_visible_refreshed_only_before_the_draw(self):
        self._catch("TestFrames.test_hover_sees_visible_written_this_frame",
                    [("scena.orchestration", "refresh_linked_visible", lambda: None)],
                    "hover reading last frame's linked visible")

    def test_fade_refusal_left_to_finish(self):
        self._catch("TestFrames.test_fades_refuse_a_linked_visible_at_the_call",
                    [("scena.transients", "_refuse_linked_visible", lambda shape, ch: None)],
                    "a fade refused only where finish swallows the error")

    def test_flip_missing_from_the_pose_pull(self):
        self._catch("TestFrames.test_flip_reaches_collision_the_frame_it_changes",
                    [(Polygon, "_scena_pose_pull", ("angle", "scale"))],
                    "a linked flip collision reads a frame late")

    def test_parked_host_refreshed(self):
        self._catch("TestFrames.test_parked_formula_is_not_run_until_resume",
                    [("scena.orchestration", "refresh_linked_channels", _plant_refresh_parked)],
                    "a parked host's formula run by the refresh (L4)")

    def test_unlinked_write_makes_an_anchor(self):
        from scena.shapes import Shape
        self._catch("TestFrames.test_unlinked_objects_stay_on_the_fast_paths",
                    [(Graphic, "_apply_flip", _plant_flip_anchor_on_write(Graphic)),
                     (Shape, "_apply_flip", _plant_flip_anchor_on_write(Shape))],
                    "a plain flip write that makes an anchor")

    def test_enabled_written_silently(self):
        self._catch("TestRefusals.test_linked_enabled_refuses_a_plain_write",
                    [("scena.entity", "_refuse_linked_channel", lambda obj, names, op: None)],
                    "a linked enabled written by a plain =")

    def test_link_write_walks_the_anchors(self):
        test = "TestLinkWriteFastPath.test_the_link_write_takes_the_flag_not_the_anchor_walk"
        self._catch(test, [("scena.style", "_refuse_linked_paint",
                            _plant_ignore_flag("_refuse_linked_paint", "scena.style"))],
                    "set_color's refusal without the flag")
        slow = _plant_ignore_flag("_refuse_linked_channel", "scena.entity")
        self._catch(test, [("scena.entity", "_refuse_linked_channel", slow),
                           ("scena.shapes", "_refuse_linked_channel", slow)],
                    "the entity refusal without the flag")

    def test_amount_skips_its_clamp(self):
        from scena.state import _AmountChannelAnchor
        self._catch("TestValues.test_line_width_clamps_like_a_formula",
                    [(_AmountChannelAnchor, "_as_is", float)],
                    "a float amount taken as it is (no clamp)")

    def test_flag_not_given_back(self):
        from scena.state import _ChannelAnchor
        test = "TestLinkWriteFastPath.test_the_flag_is_given_back"
        self._catch(test, [(_ChannelAnchor, "_takein_impl", _plant_flag_kept(_ChannelAnchor, True))],
                    "a flag left set after the link's write")
        self._catch(test, [(_ChannelAnchor, "_takein_impl", _plant_flag_kept(_ChannelAnchor, False))],
                    "a nested write that clears the outer write's flag")

if __name__ == "__main__":
    unittest.main()
