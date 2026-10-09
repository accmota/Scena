"""Appearance stamps: .glow / .shadow / .hue / .tail."""
from __future__ import annotations

import builtins
import unittest

from tests.source_support import iter_files

import skia

from scena import (
    CheapGlow,
    Circle,
    Glow,
    HueShift,
    Neon,
    Shadow,
    Sprite,
    Tail,
    Text,
    canvas,
    init,
)
from scena.stamps import (
    _TAIL_SCALE_SKIP,
    resolve_tail_angle,
    resolve_tail_size,
)

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _tick(dt: float = 1.0 / 60.0) -> None:
    """Advance world clock without the GLFW loop (for follow-tail samples)."""
    clk = builtins.clock
    clk._dt = float(dt)
    clk._frame = int(getattr(clk, "_frame", 0) or 0) + 1


class TestStampSugar(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def test_glow_true_color_none(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.glow = True
        self.assertIsInstance(c.glow, Glow)
        c.glow = "gold"
        self.assertIsInstance(c.glow, Glow)
        self.assertEqual(str(c.glow.color), str(c.glow.color))
        c.glow = False
        self.assertIsNone(c.glow)
        c.glow = CheapGlow("tomato")
        self.assertIsInstance(c.glow, CheapGlow)
        c.glow = None
        self.assertIsNone(c.glow)

    def test_shadow_true(self):
        c = Circle(center=(0, 0), radius=10)
        c.shadow = True
        self.assertIsInstance(c.shadow, Shadow)
        c.shadow = None
        self.assertIsNone(c.shadow)

    def test_hue_true_and_zero(self):
        s = Sprite("missing.png", center=(0, 0), height=32)
        s.hue = True
        self.assertIsInstance(s.hue, HueShift)
        self.assertAlmostEqual(float(s.hue.amount), 1.0 / 3.0, places=5)
        s.hue = 0
        self.assertIsNone(s.hue)
        s.hue = 0.5
        self.assertAlmostEqual(float(s.hue.amount), 0.5, places=5)

    def test_hue_shape_raises(self):
        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(TypeError) as ctx:
            c.hue = True
        self.assertIn("Sprite-only", str(ctx.exception))

    def test_tail_true_follow_and_angle(self):
        c = Circle(center=(50, 50), radius=10)
        c.tail = True
        self.assertIsInstance(c.tail, Tail)
        self.assertTrue(c._tail_follow)
        c.tail = 270
        self.assertFalse(c._tail_follow)
        self.assertAlmostEqual(float(c._tail_locked_angle), 270.0)
        c.tail = -90
        self.assertAlmostEqual(float(c._tail_locked_angle), -90.0)

    def test_visual_rejects_stamps(self):
        c = Circle(center=(0, 0), radius=10)
        for look in (Glow(), CheapGlow(), Shadow(), Tail(angle=0)):
            with self.assertRaises(TypeError) as ctx:
                c.visual = look
            self.assertIn("stamp", str(ctx.exception).lower())


class TestStampCompose(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def test_glow_survives_visual_none(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.glow = Glow("gold")
        c.visual = Neon()
        self.assertIsInstance(c.visual, Neon)
        self.assertIsInstance(c.glow, Glow)
        c.visual = None
        self.assertIsNone(c.visual)
        self.assertIsInstance(c.glow, Glow)

    def test_glow_and_shadow_together(self):
        from scena.canvas import _has_any_batchable_filter, _must_solo_draw
        from scena.style import ComposeFx

        c = Circle(center=(0, 0), radius=10)
        c.glow = True
        c.shadow = True
        self.assertIsNotNone(c.glow)
        self.assertIsNotNone(c.shadow)
        self.assertIsInstance(c.fill_filter, ComposeFx)
        self.assertIsNotNone(c.fill_filter._batch_key)
        self.assertGreater(float(c.fill_filter._batch_outset), 0.0)
        self.assertTrue(_has_any_batchable_filter(c))
        self.assertFalse(_must_solo_draw(c))

    def test_save_restore_keeps_stamps(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        neon = Neon()
        c.visual = neon
        c.glow = Glow("skyblue")
        c.save_visual()
        from scena import Halo
        c.visual = Halo()
        c.glow = None
        c.restore_visual()
        self.assertIs(c.visual, neon)
        self.assertIsInstance(c.glow, Glow)

    def test_look_like_copies_stamps(self):
        a = Circle(center=(0, 0), radius=10)
        b = Circle(center=(20, 0), radius=10)
        a.glow = Glow("cyan")
        a.shadow = Shadow()
        b.look_like(a)
        self.assertIs(b.glow, a.glow)
        self.assertIs(b.shadow, a.shadow)


    def test_glow_clear_drops_cached_image_filter(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.glow = True
        painted = c._to_skia_fill_paint()
        self.assertIsNotNone(painted.getImageFilter())
        c.glow = None
        self.assertIsNone(c.fill_filter)
        cleared = c._to_skia_fill_paint()
        self.assertIsNone(cleared.getImageFilter())

    def test_tail_then_glow_rebuilds_fill_paint(self):
        from scena.canvas import _has_any_batchable_filter, _must_solo_draw

        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.tail = True
        c._to_skia_fill_paint()
        c.glow = True
        self.assertFalse(_must_solo_draw(c))
        self.assertTrue(_has_any_batchable_filter(c))
        painted = c._to_skia_fill_paint()
        self.assertIsNotNone(painted.getImageFilter())

    def test_glow_off_after_tail_drops_filter(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.glow = True
        c.tail = True
        c._to_skia_fill_paint()
        c.glow = None
        self.assertIsNone(c.fill_filter)
        self.assertIsNone(c._to_skia_fill_paint().getImageFilter())

    def test_filtered_segment_draws_tail_before_fill(self):
        c = Circle(center=(20, 20), radius=10).set_color("coral")
        c.glow = True
        c.tail = Tail(angle=180, size=1.0)
        eng = canvas._engine
        order = []
        orig_tails = eng._draw_tail_ghosts
        orig_fill = eng._draw_fill_only

        def tails(shapes):
            order.append("tails")
            return orig_tails(shapes)

        def fill_only(shp):
            order.append("fill")
            return orig_fill(shp)

        eng._draw_tail_ghosts = tails
        eng._draw_fill_only = fill_only
        surf = skia.Surface(64, 64)
        eng.skia_canvas = surf.getCanvas()
        try:
            eng._draw_filtered_segment([c])
        finally:
            eng._draw_tail_ghosts = orig_tails
            eng._draw_fill_only = orig_fill
        self.assertEqual(order[0], "tails")
        self.assertIn("fill", order)


class TestTailFollow(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"
        _tick(1.0 / 60.0)

    def _seed(self, shape) -> None:
        """Seed _tail_prev without advancing motion."""
        resolve_tail_angle(shape)

    def test_follow_updates_from_motion(self):
        c = Circle(center=(0, 0), radius=10)
        c.tail = True
        self._seed(c)
        # Several +x samples → trail behind ≈ 180°, scale grows.
        for _ in range(8):
            _tick()
            c.move_by(10, 0)
            resolve_tail_angle(c)
        self.assertAlmostEqual(resolve_tail_angle(c) % 360.0, 180.0, delta=8.0)
        self.assertGreater(float(c._tail_speed_scale), 0.2)
        # Several +y samples → trail behind approaches 270°.
        for _ in range(16):
            _tick()
            c.move_by(0, 10)
            resolve_tail_angle(c)
        ang = resolve_tail_angle(c) % 360.0
        self.assertGreater(ang, 240.0)
        self.assertLess(ang, 300.0)

    def test_follow_stop_collapses_scale(self):
        c = Circle(center=(0, 0), radius=10)
        c.tail = True
        self._seed(c)
        for _ in range(8):
            _tick()
            c.move_by(12, 0)
            resolve_tail_angle(c)
        self.assertGreater(float(c._tail_speed_scale), _TAIL_SCALE_SKIP)
        for _ in range(30):
            _tick()
            resolve_tail_angle(c)  # zero displacement; v decays
        self.assertLess(float(c._tail_speed_scale), _TAIL_SCALE_SKIP)
        size = resolve_tail_size(c, c.tail)
        self.assertLess(size, 0.15)

    def test_follow_reverse_shrinks_then_flips(self):
        c = Circle(center=(0, 0), radius=10)
        c.tail = True
        self._seed(c)
        for _ in range(10):
            _tick()
            c.move_by(12, 0)
            resolve_tail_angle(c)
        self.assertAlmostEqual(resolve_tail_angle(c) % 360.0, 180.0, delta=15.0)
        # Reverse (−x): scale dips near zero, then trail ≈ 0° (behind new motion).
        min_scale = float(c._tail_speed_scale)
        flipped = False
        for _ in range(24):
            _tick()
            c.move_by(-12, 0)
            ang = resolve_tail_angle(c) % 360.0
            scale = float(c._tail_speed_scale)
            min_scale = min(min_scale, scale)
            if (ang < 25.0 or ang > 335.0) and scale > 0.15:
                flipped = True
                break
        self.assertLess(min_scale, 0.35)
        self.assertTrue(flipped, "trail should approach 0° after reverse")

    def test_follow_high_fps_creep_updates_heading(self):
        """Sub-1.5 DU steps still rotate heading (old per-draw floor regression)."""
        c = Circle(center=(0, 0), radius=10)
        c.tail = True
        self._seed(c)
        dt = 1.0 / 120.0
        for _ in range(40):
            _tick(dt)
            c.move_by(1.0, 0.0)  # 120 DU/s at 120 Hz; < 1.5 was the old floor
            resolve_tail_angle(c)
        self.assertAlmostEqual(resolve_tail_angle(c) % 360.0, 180.0, delta=20.0)
        self.assertGreater(float(c._tail_speed_scale), 0.1)

    def test_locked_not_overwritten(self):
        c = Circle(center=(0, 0), radius=10)
        c.tail = 180
        c.move_by(30, 0)
        self.assertAlmostEqual(resolve_tail_angle(c), 180.0, places=1)
        size = resolve_tail_size(c, c.tail)
        self.assertAlmostEqual(size, 1.2, places=2)

    def test_locked_size_ignores_motion(self):
        c = Circle(center=(0, 0), radius=10)
        c.tail = Tail(angle=90, size=1.4)
        self._seed(c)
        for _ in range(6):
            _tick()
            c.move_by(20, 0)
            resolve_tail_angle(c)
        self.assertAlmostEqual(resolve_tail_angle(c), 90.0, places=1)
        self.assertAlmostEqual(resolve_tail_size(c, c.tail), 1.4, places=2)

    def test_follow_at_ref_speed_matches_locked_size(self):
        locked = Circle(center=(0, 0), radius=10)
        locked.tail = 180
        follow = Circle(center=(0, 0), radius=10)
        follow.tail = True
        self._seed(follow)
        for _ in range(24):
            _tick()
            follow.move_by(2.0, 0)  # 120 DU/s at 60 Hz = ref speed
            resolve_tail_angle(follow)
        self.assertAlmostEqual(resolve_tail_size(locked, locked.tail), 1.2, places=2)
        self.assertAlmostEqual(
            resolve_tail_size(follow, follow.tail), 1.2, delta=0.2,
        )

    def test_tail_lambda_angle(self):
        # angle = trail direction; rotation+180 = behind the nose.
        c = Circle(center=(0, 0), radius=10)
        c.angle = 10.0
        c.tail = Tail(angle=lambda: c.angle + 180)
        self.assertFalse(c._tail_follow)
        ang = resolve_tail_angle(c)
        self.assertAlmostEqual(ang, 190.0, places=1)
        c.angle = 20.0
        ang = resolve_tail_angle(c)
        self.assertAlmostEqual(ang, 200.0, places=1)

    def test_locked_angle_is_trail_direction(self):
        """Tail(angle=90) extends the trail upward (not opposite of motion)."""
        c = Circle(center=(50, 50), radius=10)
        c.tail = Tail(angle=90, size=1.0)
        self.assertAlmostEqual(resolve_tail_angle(c), 90.0, places=1)


class TestTextGlow(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def test_glow_sugar_and_cheap(self):
        t = Text("Hi", top_left=(10, 10))
        t.glow = True
        self.assertIsInstance(t.glow, Glow)
        t.glow = CheapGlow("gold")
        self.assertIsInstance(t.glow, CheapGlow)
        with self.assertRaises(TypeError):
            t.visual = Glow()
        with self.assertRaises(TypeError):
            t.shadow = True
        with self.assertRaises(TypeError):
            t.tail = True
        with self.assertRaises(TypeError):
            t.hue = True
        t2 = Text("X", top_left=(10, 40), glow=True)
        self.assertIsInstance(t2.glow, Glow)


class TestSpriteHueTail(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def test_hue_and_glow_together(self):
        s = Sprite("missing.png", center=(0, 0), height=32)
        s.hue = 0.25
        s.glow = True
        self.assertIsNotNone(s.hue)
        self.assertIsNotNone(s.glow)
        surf = skia.Surface(64, 64)
        s.draw(surf.getCanvas())

    def test_tail_with_halo_costume(self):
        from scena import Halo
        s = Sprite("missing.png", center=(40, 40), height=32)
        s.visual = Halo()
        s.tail = Tail(angle=90, size=1.0)
        surf = skia.Surface(128, 128)
        s.draw(surf.getCanvas())
        self.assertIsInstance(s.visual, Halo)
        self.assertIsInstance(s.tail, Tail)

    def test_shadow_then_glow_stays_on_filter_path(self):
        from scena.canvas import _has_any_batchable_filter, _must_solo_draw
        from scena.style import ComposeFx

        s = Sprite("missing.png", center=(0, 0), height=32)
        s.shadow = True
        self.assertTrue(_has_any_batchable_filter(s))
        self.assertFalse(_must_solo_draw(s))
        s.glow = True
        self.assertIsInstance(s.fill_filter, ComposeFx)
        self.assertTrue(_has_any_batchable_filter(s))
        self.assertFalse(_must_solo_draw(s))
        self.assertGreater(float(s.fill_filter._batch_outset), 0.0)
        surf = skia.Surface(64, 64)
        s.draw(surf.getCanvas())

    def test_tail_with_glow_not_solo(self):
        from scena.canvas import _has_any_batchable_filter, _must_solo_draw

        s = Sprite("missing.png", center=(0, 0), height=32)
        s.tail = True
        self.assertFalse(_must_solo_draw(s))
        s.glow = True
        self.assertFalse(_must_solo_draw(s))
        self.assertTrue(_has_any_batchable_filter(s))


# Stamp looks that raise on ``.visual =`` (see ``scena.stamps.is_stamp_visual``).
_STAMP_NAMES = ("Glow", "CheapGlow", "Shadow", "HueShift", "Tail")


def _stamp_on_visual_sites(tree):
    """Yield line numbers where a stamp constructor is assigned to ``.visual``.

    Covers ``x.visual = Stamp(...)``, ``setattr(x, "visual", Stamp(...))`` and
    ``visual=Stamp(...)`` kwargs. Sites inside a ``try`` body are skipped —
    smoke scripts assign them on purpose to show the stamp hint.
    """
    import ast

    def stamp_call(v):
        if not isinstance(v, ast.Call):
            return False
        f = v.func
        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
        return name in _STAMP_NAMES

    def walk(node, in_try):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and not in_try:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if stamp_call(node.value) and any(
                isinstance(t, ast.Attribute) and t.attr == "visual" for t in targets
            ):
                yield node.lineno
        if isinstance(node, ast.Call) and not in_try:
            f = node.func
            if (
                isinstance(f, ast.Name) and f.id == "setattr" and len(node.args) == 3
                and isinstance(node.args[1], ast.Constant) and node.args[1].value == "visual"
                and stamp_call(node.args[2])
            ):
                yield node.lineno
            for kw in node.keywords:
                if kw.arg == "visual" and stamp_call(kw.value):
                    yield kw.value.lineno
        if isinstance(node, ast.Try):
            for child in node.body:
                yield from walk(child, True)
            for child in node.handlers + node.orelse + node.finalbody:
                yield from walk(child, in_try)
            return
        for child in ast.iter_child_nodes(node):
            yield from walk(child, in_try)

    yield from walk(tree, False)


class TestScriptsUseStampProperties(unittest.TestCase):
    """Benches/examples must not assign stamps to ``.visual``.

    The runtime guard only fires when the line executes, so a stale bench can
    ship and crash (or, behind a flag / rare branch, never get noticed). Scan
    the source instead.
    """

    def test_stamp_name_list_matches_runtime_guard(self):
        import scena
        from scena.stamps import is_stamp_visual

        for name in _STAMP_NAMES:
            self.assertTrue(is_stamp_visual(getattr(scena, name)()), name)

    def test_scan_detects_all_spellings(self):
        import ast

        src = (
            "a.visual = Glow()\n"
            "setattr(a, 'visual', CheapGlow())\n"
            "Sprite(visual=Tail())\n"
            "a.visual = Halo()\n"
            "try:\n    a.visual = Shadow()\nexcept TypeError:\n    pass\n"
        )
        self.assertEqual(list(_stamp_on_visual_sites(ast.parse(src))), [1, 2, 3])

    def test_no_stamp_on_visual_in_scripts(self):
        import ast
        import pathlib

        repo = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for top in ("scripts", "examples"):
            for path in map(pathlib.Path, iter_files(repo / top, ".py", recursive=True)):
                rel = path.relative_to(repo)
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                offenders += [f"{rel}:{ln}" for ln in _stamp_on_visual_sites(tree)]
        self.assertEqual(
            offenders, [],
            "stamp assigned to .visual — use .glow / .shadow / .hue / .tail",
        )


if __name__ == "__main__":
    unittest.main()
