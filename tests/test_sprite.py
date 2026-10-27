"""Slice 4–6 Sprite / Sheet / play / atlas / hitbox / overlay looks.

Run headless:

    python -m unittest tests.test_sprite -v
"""

import math
import os
import json
import tempfile
import unittest
import warnings

import skia

from tests.media_support import media

from scena import (
    Circle, Sprite, Sheet, Rect, Svg, clock, collide, tween, canvas, group, init,
    Glow, CheapGlow, Shadow, Halo, HostGlow, Tail, Beat, ElectricField, ElectricBolt, Shield,
    Flame, Water, Neon, Paint, Metal, Swell, Aurora, Wave, Extrude,
    MultiBorder, OrganicOutline, Tracer,
    HueShift, Grayscale, Recolor, Aura, EmissiveBloom, Rim,
    DashRing, GearShell, Laser, Ink, InkBleed,
)
from scena.shapes import Entity, Graphic, Shape
from scena.sprite import reset_sprite_caches, _sprite_ellipse_scale, _SPRITE_SHIELD_SCALE
from scena.canvas import (
    ScenaCanvas,
    _approx_draw_aabb,
    _aabb_from_oriented,
    _aabb_contains,
    _expand_aabb_for_shield_oval,
    _filter_outset,
    _pad_aabb,
)
from scena.style import is_sprite_body
from scena.recipes import _forcefield_kind, _ellipse_params
from scena.atlas import _FRAME_FX_CACHE
from scena.collision import (
    PrimKind,
    get_collision_system,
    reset_collision_system,
    snapshot_shape,
    _prim_contains_point,
)
from scena.process import reset_process_scheduler, tick_processes
from scena.events import cleanup_global_event_system
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


def _frame(real_dt=0.1):
    clock.advance(real_dt)
    tick_processes()


def _write_grid_png(path, *, cell=16, cols=2, rows=2):
    """Row-major cells: red, green / blue, yellow."""
    w, h = cell * cols, cell * rows
    info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    colors = (
        skia.ColorRED, skia.ColorGREEN,
        skia.ColorBLUE, skia.ColorYELLOW,
    )
    for i in range(cols * rows):
        col, row = i % cols, i // cols
        paint = skia.Paint(Color=colors[i % len(colors)])
        c.drawRect(skia.Rect.MakeXYWH(col * cell, row * cell, cell, cell), paint)
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _write_rect_png(path, px_w, px_h, color=skia.ColorWHITE):
    info = skia.ImageInfo.Make(px_w, px_h, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    surf.getCanvas().drawPaint(skia.Paint(Color=color))
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _write_inset_png(path, px_w, px_h, rect):
    """Transparent canvas with one opaque rect ``(x, y, w, h)``."""
    info = skia.ImageInfo.Make(px_w, px_h, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    x, y, w, h = rect
    c.drawRect(
        skia.Rect.MakeXYWH(x, y, w, h),
        skia.Paint(Color=skia.ColorWHITE, AntiAlias=False),
    )
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _ellipse_gram(rx, ry, ang):
    """Gram matrix of the world ellipse linear map (M @ M.T as xx, xy, yy)."""
    c, sn = math.cos(ang), math.sin(ang)
    m00, m01 = c * rx, -sn * ry
    m10, m11 = sn * rx, c * ry
    return (
        m00 * m00 + m01 * m01,
        m00 * m10 + m01 * m11,
        m10 * m10 + m11 * m11,
    )


def _write_disk_png(path, side=32, radius=14):
    """Filled opaque disk on transparent. Auto-hitbox should pick a circle."""
    info = skia.ImageInfo.Make(side, side, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    paint = skia.Paint(Color=skia.ColorWHITE, AntiAlias=False)
    c.drawCircle(side * 0.5, side * 0.5, float(radius), paint)
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _write_blob_strip(path, *, cell=32, blobs=None):
    """Horizontal strip of cells: opaque axis-aligned blobs on transparent.

    Default blobs differ in size so a per-frame re-fit would move extents.
    """
    if blobs is None:
        blobs = (
            (12, 20, 8, 8),
            (4, 4, 24, 24),
            (13, 2, 6, 28),
            (2, 13, 28, 6),
        )
    cols = len(blobs)
    w, h = cell * cols, cell
    info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    paint = skia.Paint(Color=skia.ColorWHITE, AntiAlias=False)
    for i, (bx, by, bw, bh) in enumerate(blobs):
        c.drawRect(skia.Rect.MakeXYWH(i * cell + bx, by, bw, bh), paint)
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _write_padded_png(path, *, canvas_w=64, canvas_h=32, blob=(22, 10, 20, 12)):
    """Opaque blob on a larger transparent canvas (padded character art)."""
    info = skia.ImageInfo.Make(
        canvas_w, canvas_h, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType,
    )
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    paint = skia.Paint(Color=skia.ColorWHITE, AntiAlias=False)
    bx, by, bw, bh = blob
    c.drawRect(skia.Rect.MakeXYWH(bx, by, bw, bh), paint)
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _write_l_png(path, side=32):
    """Opaque L: left column + bottom row. Inner corner is transparent."""
    info = skia.ImageInfo.Make(side, side, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    paint = skia.Paint(Color=skia.ColorWHITE)
    thick = side // 4
    c.drawRect(skia.Rect.MakeXYWH(0, 0, thick, side), paint)
    c.drawRect(skia.Rect.MakeXYWH(0, side - thick, side, thick), paint)
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _write_rgba_png(path, px_w, px_h, color):
    """Solid rectangle; ``color`` is an 8-bit RGBA tuple (unpremul)."""
    info = skia.ImageInfo.Make(px_w, px_h, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    r, g, b, a = color
    paint = skia.Paint(Color=skia.ColorSetARGB(a, r, g, b))
    surf.getCanvas().drawPaint(paint)
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _surface_center_rgba(surf):
    img = surf.makeImageSnapshot()
    w, h = img.width(), img.height()
    info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    buf = bytearray(w * h * 4)
    if not img.readPixels(info, buf, w * 4, 0, 0):
        raise AssertionError("readPixels failed")
    i = ((h // 2) * w + (w // 2)) * 4
    return tuple(buf[i:i + 4])


class SpriteTestCase(unittest.TestCase):
    def setUp(self):
        reset_sprite_caches()
        reset_process_scheduler()
        reset_collision_system()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        self._owned = []
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        for obj in self._owned:
            try:
                if getattr(obj, "is_alive", False):
                    obj.destroy()
            except Exception:
                pass
        self._owned.clear()
        self._tmp.cleanup()
        reset_process_scheduler()
        reset_collision_system()
        reset_sprite_caches()
        cleanup_global_event_system()

    def track(self, obj):
        self._owned.append(obj)
        return obj

    def tmp(self, name):
        return os.path.normpath(os.path.join(self._tmp.name, name))


class TestNoGeometryModel(SpriteTestCase):
    """A7 (RA 0.9.0): Sprite carried a dead ``model`` slot, so
    ``sprite.model = "x"`` was taken while Text refused it (a Shape field)."""

    def test_model_refuses_like_text(self):
        from scena import Svg
        for s in (self.track(Sprite(media("space", "enemyGreen1.png"))), self.track(Svg())):
            kind = type(s).__name__
            with self.assertRaisesRegex(AttributeError, f"{kind} has no field 'model' "
                                        r"\(a Shape field\)"):
                s.model = "x"
            with self.assertRaisesRegex(AttributeError, "so @= has nothing to link"):
                s["model"] @= (lambda: 1)
            self.assertIsNone(getattr(s, "model", None))

    def test_public_slots_are_live_fields(self):
        """Class guard: a public ``__slots__`` name is a descriptor that takes
        writes, so a dead one hides a refusal. Only ``group`` (every Graphic)
        and ``model`` (a Shape's geometry discriminant) are slots."""
        import scena
        from scena.entity import Graphic
        for kind_name in scena.__all__:
            kind = getattr(scena, kind_name)
            if not (isinstance(kind, type) and issubclass(kind, Graphic)):
                continue
            public = {name for base in kind.__mro__
                      for name in (base.__dict__.get("__slots__") or ())
                      if not name.startswith("_")}
            allowed = {"group", "model"} if issubclass(kind, Shape) else {"group"}
            with self.subTest(kind=kind_name):
                self.assertLessEqual(public, allowed)


class TestScaleKeepsTheGivenSize(SpriteTestCase):
    """Guia pose table (PM6): .scale multiplies the drawing and the collider;
    .width / .height stay the size the author gave; .box is the drawn size."""

    def test_height_stays_box_and_hitbox_scale(self):
        s = self.track(Sprite(media("space", "enemyGreen1.png"), height=40, center=(0, 0)))
        hb0 = s.hitbox.box.height
        s.scale = 1.5
        self.assertAlmostEqual(s.height, 40.0)
        self.assertAlmostEqual(s.box.height, 60.0)
        self.assertAlmostEqual(s.hitbox.box.height, 1.5 * hb0)


class TestIdentityAndPlaceholder(SpriteTestCase):
    def test_sprite_is_graphic_not_shape(self):
        s = self.track(Sprite(center=(0, 0), size=32))
        self.assertIsInstance(s, Graphic)
        self.assertIsInstance(s, Entity)
        self.assertNotIsInstance(s, Shape)
        self.assertNotIsInstance(s, Circle)
        c = self.track(Circle(center=(0, 0), radius=10))
        self.assertIsInstance(c, Graphic)
        self.assertIsInstance(c, Entity)
        self.assertIsInstance(c, Shape)
        self.assertNotIsInstance(c, Sprite)

    def test_placeholder_is_legal_no_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s = self.track(Sprite(center=(10, 20), size=40))
        missing = [w for w in caught if "not found" in str(w.message)]
        self.assertEqual(missing, [])
        self.assertTrue(s._placeholder)
        self.assertEqual(float(s.center.x), 10)
        self.assertEqual(float(s.center.y), 20)
        self.assertTrue(s.is_alive)

    def test_missing_file_warns_once_and_stays_an_actor(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            a = self.track(Sprite("definitely_missing_slice4.png", center=(0, 0), size=24))
            b = self.track(Sprite("definitely_missing_slice4.png", center=(5, 0), size=24))
        msgs = [w for w in caught if "not found" in str(w.message)]
        self.assertEqual(len(msgs), 1)
        self.assertTrue(a._placeholder)
        self.assertTrue(b._placeholder)
        a.hp = 3
        a.move_to(40, 50)
        self.assertEqual(float(a.center.x), 40)
        self.assertEqual(float(a.hp), 3)

    def test_unknown_ctor_kwargs_raise(self):
        with self.assertRaises(TypeError) as ctx:
            Sprite(center=(0, 0), radius=5)
        msg = str(ctx.exception)
        self.assertIn("radius", msg)
        self.assertIn("Circle", msg)

        with self.assertRaises(TypeError) as ctx:
            Sprite(center=(0, 0), aaa=1, group="badkw")
        self.assertIn("aaa", str(ctx.exception))
        self.assertEqual(len(group["badkw"]), 0)

    def test_sheet_does_not_place(self):
        path = self.tmp("cell.png")
        _write_rect_png(path, 16, 16)
        sheet = Sheet(path, cell=(16, 16))
        self.assertNotIsInstance(sheet, Entity)
        self.assertEqual(sheet.nframes, 1)

    def test_same_file_shares_decoded_image(self):
        path = self.tmp("shared.png")
        _write_rect_png(path, 8, 8, skia.ColorBLUE)
        a = self.track(Sprite(path, center=(0, 0), size=16))
        b = self.track(Sprite(path, center=(10, 0), size=16))
        self.assertIs(a.sheet.image, b.sheet.image)

    def test_path_only_sprites_share_interned_catalog(self):
        path = self.tmp("shot.png")
        _write_rect_png(path, 8, 8, skia.ColorRED)
        a = self.track(Sprite(path, height=18, center=(0, 0), group="sting"))
        b = self.track(Sprite(path, height=18, center=(10, 0), group="sting"))
        self.assertIs(a.sheet, b.sheet)
        self.assertIs(a.sheet.image, b.sheet.image)
        self.assertTrue(a.sheet._interned)
        self.assertTrue(a.sheet._shared)
        self.assertFalse(a._owns_sheet)

    def test_placeholder_sprites_share_interned_catalog(self):
        a = self.track(Sprite(center=(0, 0), size=16))
        b = self.track(Sprite(center=(10, 0), size=16))
        self.assertIs(a.sheet, b.sheet)
        self.assertTrue(a.sheet._interned)

    def test_layout_strip_does_not_intern(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        a = self.track(Sprite(Sheet(path, cols=4, fps=8), center=(0, 0), size=16))
        b = self.track(Sprite(Sheet(path, cols=4, fps=8), center=(10, 0), size=16))
        self.assertIsNot(a.sheet, b.sheet)
        self.assertIs(a.sheet.image, b.sheet.image)

    def test_interned_sheet_refuses_strip(self):
        run = self.tmp("coin.png")
        idle = self.tmp("idle.png")
        _write_rect_png(run, 8, 8)
        _write_grid_png(idle, cell=8, cols=2, rows=1)
        a = self.track(Sprite(run, center=(0, 0), size=16))
        b = self.track(Sprite(run, center=(10, 0), size=16))
        self.assertIs(a.sheet, b.sheet)
        with self.assertRaises(TypeError) as ctx:
            a.sheet.strip("idle", idle, cols=2, fps=4)
        self.assertIn("interned", str(ctx.exception))
        self.assertIs(a.sheet, b.sheet)
        self.assertEqual(a.sheet.nframes, 1)
        self.assertEqual(b.sheet.nframes, 1)


class TestSizeApi(SpriteTestCase):
    def test_height_keeps_aspect(self):
        path = self.tmp("wide.png")
        _write_rect_png(path, 32, 16)
        s = self.track(Sprite(path, center=(0, 0), height=40))
        self.assertAlmostEqual(float(s.height), 40)
        self.assertAlmostEqual(float(s.width), 80)

    def test_width_keeps_aspect(self):
        path = self.tmp("wide.png")
        _write_rect_png(path, 32, 16)
        s = self.track(Sprite(path, center=(0, 0), width=20))
        self.assertAlmostEqual(float(s.width), 20)
        self.assertAlmostEqual(float(s.height), 10)

    def test_size_is_longer_side(self):
        path = self.tmp("wide.png")
        _write_rect_png(path, 32, 16)
        s = self.track(Sprite(path, center=(0, 0), size=50))
        self.assertAlmostEqual(float(s.width), 50)
        self.assertAlmostEqual(float(s.height), 25)
        s.size = 100
        self.assertAlmostEqual(float(s.width), 100)
        self.assertAlmostEqual(float(s.height), 50)

    def test_width_and_height_stretch(self):
        path = self.tmp("sq.png")
        _write_rect_png(path, 16, 16)
        s = self.track(Sprite(path, center=(0, 0), width=10, height=40))
        self.assertAlmostEqual(float(s.width), 10)
        self.assertAlmostEqual(float(s.height), 40)

    def test_size_with_width_raises(self):
        with self.assertRaises(TypeError) as ctx:
            Sprite(center=(0, 0), size=10, width=10)
        self.assertIn("size=", str(ctx.exception))

    def test_zero_height_is_collapsed_negative_width_raises(self):
        s = self.track(Sprite(center=(0, 0), height=0))
        self.assertEqual(float(s.height), 0.0)
        with self.assertRaises(ValueError):
            Sprite(center=(0, 0), width=-4)

    def test_width_height_are_bare_floats(self):
        s = self.track(Sprite(center=(0, 0), width=40, height=20))
        self.assertIsInstance(s.width, float)
        self.assertIsInstance(s.height, float)
        self.assertEqual(s.width, 40.0)
        self.assertEqual(s.height, 20.0)

    def test_bracket_link_width(self):
        from scena.state import LinkedAttributeError, Attribute
        s = self.track(Sprite(center=(0, 0), width=40, height=20))
        s["width"] @= Attribute(80.0)
        self.assertTrue(s["width"].is_linked)
        self.assertEqual(s.width, 80.0)
        with self.assertRaises(LinkedAttributeError):
            s.width = 10
        s["width"].unlink()
        s.width = 12
        self.assertEqual(s.width, 12.0)

    def test_rotation_and_scale_are_linkable(self):
        from scena.state import Attribute

        s = self.track(Sprite(center=(0, 0), width=40, height=20))
        heading = Attribute(30.0)
        s["angle"] @= heading
        self.assertTrue(s["angle"].is_linked)
        self.assertAlmostEqual(s.angle, 30.0)
        heading.value = 90.0
        self.assertAlmostEqual(s.angle, 90.0)
        s["angle"].unlink()
        zoom = Attribute(1.0)
        s["scale"] @= zoom
        zoom.value = 2.0
        self.assertAlmostEqual(s.scale, 2.0)
        cx, cy, w, h, _ = s._oriented_frame()
        self.assertAlmostEqual(w, 80.0)
        self.assertAlmostEqual(h, 40.0)

    def test_plain_blit_pulls_linked_rotation_and_scale(self):
        """Plain-blit must refresh PropertyAnchors before reading raw pose.

        ``_blit_plain`` skips ``Graphic.draw``, which is the only place that
        used to call ``_pull_property_anchors``. Without a pull, a linked
        ``angle`` / ``scale`` stays stale while the source moves — e.g.
        ``ship["angle"] @= aim``. Do **not** read ``.angle`` / ``.scale``
        between the source write and the blit (that would mask the bug).
        """
        from scena.state import Attribute

        path = self.tmp("plain.png")
        _write_rect_png(path, 16, 16)
        s = self.track(Sprite(path, center=(0, 0), width=40, height=20))
        self.assertTrue(s._plain_blit)

        heading = Attribute(15.0)
        s["angle"] @= heading
        zoom = Attribute(1.0)
        s["scale"] @= zoom
        # Seed pull at link time (install writes through).
        self.assertAlmostEqual(s._rotation, 15.0)
        self.assertAlmostEqual(s._scale, 1.0)

        heading.value = 90.0
        zoom.value = 2.0
        # Stale raw slots until something pulls — prove the gap still exists
        # *before* blit, then that blit itself closes it.
        self.assertAlmostEqual(s._rotation, 15.0)
        self.assertAlmostEqual(s._scale, 1.0)

        info = skia.ImageInfo.Make(8, 8, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        s._blit_plain(surf.getCanvas())

        self.assertAlmostEqual(s._rotation, 90.0)
        self.assertAlmostEqual(s._scale, 2.0)
        self.assertAlmostEqual(s._draw_angle(), 90.0)
        sx, sy = s._pixel_scale()
        self.assertAlmostEqual(sx, 2.0 * (40.0 / 16.0))
        self.assertAlmostEqual(sy, 2.0 * (20.0 / 16.0))

    def test_scale_is_pose_zoom_not_pixel_map(self):
        s = self.track(Sprite(center=(0, 0), width=40, height=20))
        self.assertAlmostEqual(s._oriented_frame()[2], 40)
        s.scale_to(2)
        cx, cy, w, h, _ = s._oriented_frame()
        self.assertAlmostEqual(w, 80)
        self.assertAlmostEqual(h, 40)
        self.assertAlmostEqual(float(s.width), 40)

    def test_is_collapsed_normal_and_scale_zero(self):
        s = self.track(Sprite(center=(0, 0), width=40, height=20))
        self.assertFalse(s.is_collapsed)
        s.scale_to(0)
        self.assertTrue(s.is_collapsed)
        self.assertAlmostEqual(float(s.width), 40.0)

    def test_rotate_about_orbits_center(self):
        s = self.track(Sprite(center=(100, 0), width=10, height=10))
        s.rotate_by(90, about=(0, 0))
        self.assertAlmostEqual(s.center.x, 0.0, places=5)
        self.assertAlmostEqual(s.center.y, 100.0, places=5)
        self.assertAlmostEqual(s.angle, 90.0)

    def test_rotate_about_linked_center_raises_without_force(self):
        from scena.state import LinkedAttributeError
        from scena.shapes import Point
        src = Point(100, 0)
        s = self.track(Sprite(center=(100, 0), width=10, height=10))
        s["center"] @= src
        with self.assertRaises(LinkedAttributeError):
            s.rotate_by(90, about=(0, 0))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            s.rotate_by(90, about=(0, 0), force=True)
        self.assertAlmostEqual(s.center.x, 0.0, places=5)
        self.assertAlmostEqual(s.center.y, 100.0, places=5)

    def test_scale_about_orbits_center(self):
        s = self.track(Sprite(center=(100, 0), width=10, height=10))
        s.scale_by(2, about=(0, 0))
        self.assertAlmostEqual(s.center.x, 200.0, places=5)
        self.assertAlmostEqual(s.center.y, 0.0, places=5)
        self.assertAlmostEqual(s.scale, 2.0)


class TestClipOnTheExactFrame(SpriteTestCase):
    """PB3 (graphics review): the clip playhead truncated summed time,
    ``int(elapsed * fps)``, so a clip frame due on a whole game frame showed
    one game frame late depending on float rounding: the PM8 class that
    ``process.reached`` closed for timers, missed for the playhead.

    Every (game fps, clip fps, clip frame m) where clip frame m is due on a
    whole game frame. Off-by-one cases are shrink-only
    (``graphics_known.CLIP_DUE``, keyed by game fps and clip fps)."""

    GAME_FPS = (24, 30, 50, 60, 120, 144)
    CLIP_FPS = (4, 6, 8, 10, 12, 15, 24, 30)

    def late_cases(self) -> dict:
        path = self.tmp("due.png")
        _write_grid_png(path, cell=8, cols=4, rows=2)
        out = {}
        for game in self.GAME_FPS:
            for fps in self.CLIP_FPS:
                if game % fps:
                    continue                    # clip frames never land on a game frame
                sheet = Sheet(path, cell=(8, 8))
                sheet.clip("run", list(range(8)), fps=fps)
                s = self.track(Sprite(sheet, center=(0, 0)))
                s.play("run")                     # starts at the current world time
                per = game // fps                 # game frames per clip frame
                late = []
                for m in range(1, 24):
                    for _ in range(per):
                        clock.advance(1.0 / game)
                    if s.frame != m % 8:
                        late.append(m)
                s.destroy()
                if late:
                    out[f"game {game} | clip {fps}"] = ",".join(map(str, late[:6]))
        return out

    def test_clip_frame_m_shows_on_its_game_frame(self):
        from tests.graphics_known import shrink_only
        shrink_only(self, self.late_cases(), "CLIP_DUE")


class TestClipTimingAndSize(SpriteTestCase):
    """Graphics review batch 8b: PB4, PB5, PB6, PB9, PB14."""

    def _sheet(self):
        path = self.tmp("t.png")
        _write_grid_png(path, cell=8, cols=4, rows=2)
        sh = Sheet(path, cell=(8, 8))
        sh.clip("atk", [0, 1, 2], fps=10)
        sh.clip("idle", [4, 5, 6, 7], fps=10)
        return sh

    def test_a_hidden_sprite_can_replay_a_one_shot(self):
        # PB4: the end was settled only by a draw; play() thought it still ran.
        s = self.track(Sprite(self._sheet(), center=(0, 0)))
        s.visible = False
        s.play("atk", loops=1)
        clock.advance(0.7)
        s.play("atk", loops=1)
        self.assertEqual(s._play_name, "atk")
        self.assertAlmostEqual(s._play_elapsed(), 0.0)

    def test_next_starts_at_the_boundary_however_late_the_read(self):
        # PB4: next= started at the first read after the end.
        s = self.track(Sprite(self._sheet(), center=(0, 0)))
        s.play("atk", loops=1, next="idle")
        clock.advance(0.5)                     # 0.3 s of atk, then 0.2 s of idle
        self.assertEqual(s.frame, 6)

    def test_play_while_frozen_shows_the_new_clip_start(self):
        # PB5: a frozen sprite kept the old clip's phase.
        s = self.track(Sprite(self._sheet(), center=(0, 0)))
        s.play("idle")
        clock.advance(0.25)
        s.time_scale = 0
        s.play("atk")
        self.assertEqual(s.frame, 0)

    def test_time_scale_is_validated(self):
        # PB6: -1 and NaN froze silently, inf crashed every draw, True passed.
        s = self.track(Sprite(self._sheet(), center=(0, 0)))
        for bad in (-1, float("nan"), float("inf"), True, "fast"):
            with self.assertRaises((TypeError, ValueError)):
                s.time_scale = bad

    def test_size_after_a_collapse_keeps_the_aspect(self):
        # PB14: size = 0 then size = 20 gave a square.
        s = self.track(Sprite(media("space", "enemyGreen1.png"), center=(0, 0), size=40))
        aspect = s.height / s.width
        s.size = 0
        s.size = 20
        self.assertAlmostEqual(s.height / s.width, aspect)

    def test_new_svg_art_keeps_its_aspect(self):
        # PB9: art of another aspect was stretched into the old box.
        from scena import Svg
        wide = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20"/></svg>'
        tall = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="40"><rect width="20" height="40"/></svg>'
        s = self.track(Svg(wide, center=(0, 0), height=20))
        s.svg = tall
        self.assertAlmostEqual(s.height, 20.0)
        self.assertAlmostEqual(s.width, 10.0)


class TestPlayAndSheet(SpriteTestCase):
    def _sheet(self):
        path = self.tmp("hero.png")
        _write_grid_png(path, cell=16, cols=2, rows=2)
        sh = Sheet(path, cell=(16, 16))
        sh.clip("idle", [0, 1, 2], fps=10)
        sh.clip("hit", [3], fps=1)
        return sh

    def _bare_sheet(self):
        path = self.tmp("bare.png")
        _write_grid_png(path, cell=16, cols=2, rows=2)
        return Sheet(path, cell=(16, 16))

    def test_cell_frame_count_and_index(self):
        sh = self._sheet()
        self.assertEqual(sh.nframes, 4)
        s = self.track(Sprite(sh, center=(0, 0), frame=2, size=32))
        self.assertEqual(s.frame, 2)

    def test_frame_out_of_range(self):
        sh = self._sheet()
        with self.assertRaises(ValueError) as ctx:
            Sprite(sh, center=(0, 0), frame=9, group="oor")
        self.assertIn("out of range", str(ctx.exception))
        self.assertEqual(len(group["oor"]), 0)

    def test_unknown_clip_lists_names(self):
        sh = self._sheet()
        s = self.track(Sprite(sh, center=(0, 0), size=32))
        with self.assertRaises(ValueError) as ctx:
            s.play("walk")
        msg = str(ctx.exception)
        self.assertIn("walk", msg)
        self.assertIn("idle", msg)

    def test_play_advances_with_world_time(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))
        s.play("idle")
        self.assertEqual(s.frame, 0)
        clock.advance(0.15)  # 1.5 frames at 10 fps → index 1
        self.assertEqual(s.frame, 1)
        clock.advance(0.10)  # 2.5 → index 2
        self.assertEqual(s.frame, 2)
        clock.advance(0.10)  # 3.5 → wrap to 0
        self.assertEqual(s.frame, 0)

    def test_play_same_clip_every_frame_does_not_reset(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))
        s.play("idle")
        clock.advance(0.25)  # 2.5 → frame 2
        self.assertEqual(s.frame, 2)
        s.play("idle")
        s.play("idle")
        self.assertEqual(s.frame, 2)

    def test_play_min_hold_blocks_early_switch(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))
        s.play("idle", min_hold=0.2)
        clock.advance(0.05)
        s.play("hit")
        self.assertEqual(s._play_name, "idle")
        clock.advance(0.2)
        s.play("hit")
        self.assertEqual(s._play_name, "hit")

    def test_play_resume_continues_phase(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))
        s.play("idle", resume=True)
        clock.advance(0.25)  # frame 2 at 10 fps
        self.assertEqual(s.frame, 2)
        s.play("hit")
        s.play("idle", resume=True)
        self.assertEqual(s._play_name, "idle")
        self.assertEqual(s.frame, 2)

    def test_play_without_resume_restarts(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))
        s.play("idle")
        clock.advance(0.25)
        s.play("hit")
        s.play("idle")
        self.assertEqual(s.frame, 0)

    def test_tilt_pivot_is_hitbox_anchor(self):
        from scena.sprite import _anchor_on_aabb

        s = self.track(Sprite(
            self._sheet(), center=(0, 0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom",
        ))
        s._ensure_auto_baked()
        aabb = s._local_prims_aabb()
        w, h = s._hitbox_pose_wh()
        ax, ay = _anchor_on_aabb(*aabb, "bottom")
        px, py = s._tilt_pivot_local()
        self.assertAlmostEqual(px, ax * abs(float(w)), places=4)
        self.assertAlmostEqual(py, ay * abs(float(h)), places=4)
        # Opaque cell: baked bottom is the design-box bottom.
        self.assertAlmostEqual(py, -0.5 * abs(float(s.height)), places=3)

        path = self.tmp("padded.png")
        _write_padded_png(path, canvas_w=64, canvas_h=64, blob=(20, 8, 24, 40))
        padded = self.track(Sprite(
            path, center=(0, 0), width=64, height=64,
            hitbox_shape="rect", hitbox_anchor="bottom",
        ))
        padded._ensure_auto_baked()
        paabb = padded._local_prims_aabb()
        pw, ph = padded._hitbox_pose_wh()
        pax, pay = _anchor_on_aabb(*paabb, "bottom")
        ppx, ppy = padded._tilt_pivot_local()
        self.assertAlmostEqual(ppx, pax * abs(float(pw)), places=4)
        self.assertAlmostEqual(ppy, pay * abs(float(ph)), places=4)
        # Transparent margin: feet are above the PNG bottom.
        self.assertGreater(ppy, -0.5 * abs(float(ph)) + 1.0)

    def test_tilt_contact_does_not_move_center(self):
        """Seating the art does not move the solver center."""
        from scena.collision import TouchingContact
        from scena import Vec2

        s = self.track(Sprite(
            self._sheet(), center=(10.0, 20.0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom",
        ))
        s._ensure_auto_baked()
        cx0, cy0 = float(s.center.x), float(s.center.y)
        s.tilt = TouchingContact(
            other=s,
            side="bottom",
            slope_angle=22.0,
            normal=Vec2(0.375, -0.927),
            tangent=Vec2(0.927, 0.375),
            point=(18.0, 5.0),
        )
        self.assertAlmostEqual(s.tilt, 22.0)
        self.assertAlmostEqual(float(s.center.x), cx0, places=5)
        self.assertAlmostEqual(float(s.center.y), cy0, places=5)

        grounded = TouchingContact(
            other=s,
            side="bottom",
            slope_angle=22.0,
            normal=Vec2(0.375, -0.927),
            tangent=Vec2(0.927, 0.375),
            point=(18.0, 5.0),
        )
        s._collision_set_touching(frozenset({"bottom"}), (grounded,))
        s.tilt = "ground"
        self.assertAlmostEqual(s.tilt, 22.0)
        self.assertAlmostEqual(float(s.center.x), cx0, places=5)
        self.assertAlmostEqual(float(s.center.y), cy0, places=5)

    def test_tilt_seats_bottom_along_normal_on_slope(self):
        """Feet drop onto the ramp along the normal, not sideways to the corner."""
        import math
        from scena.collision import TouchingContact
        from scena import Vec2

        s = self.track(Sprite(
            self._sheet(), center=(10.0, 20.0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom",
        ))
        s._ensure_auto_baked()
        cx, cy = float(s.center.x), float(s.center.y)
        px, py = s._tilt_pivot_local()
        aabb = s._local_prims_aabb()
        w, h = s._hitbox_pose_wh()
        w, h = abs(float(w)), abs(float(h))
        corner_x = aabb[2] * w
        theta = math.radians(22.0)
        nx, ny = math.sin(theta), -math.cos(theta)
        tx, ty = math.cos(theta), math.sin(theta)
        # Resting corner of the upright box: same bottom y, right end.
        point = (cx + corner_x, cy + py)
        contact = TouchingContact(
            other=s,
            side="bottom",
            slope_angle=22.0,
            normal=Vec2(nx, ny),
            tangent=Vec2(tx, ty),
            point=point,
        )
        s._collision_set_touching(frozenset({"bottom"}), (contact,))
        s.tilt = "ground"
        sx, sy = s._tilt_seat_local(cx, cy)
        # Along the normal, and the planted anchor lies on the plane.
        self.assertAlmostEqual(sx * tx + sy * ty, 0.0, places=4)
        planted_x = cx + px + sx
        planted_y = cy + py + sy
        gap = (planted_x - point[0]) * nx + (planted_y - point[1]) * ny
        self.assertAlmostEqual(gap, 0.0, places=4)
        half = corner_x - px
        self.assertGreater(half, 1.0)
        self.assertAlmostEqual(math.hypot(sx, sy), half * math.sin(theta), places=3)
        # Not the old slide of the anchor onto the corner.
        self.assertLess(abs(sx), half * 0.5)

        # Heading stays about center; the seat is still along the world normal.
        s.angle = 40.0
        draw = math.radians(s._draw_angle())
        lsx, lsy = s._tilt_seat_local(cx, cy)
        c, sn = math.cos(draw), math.sin(draw)
        wx, wy = c * lsx - sn * lsy, sn * lsx + c * lsy
        self.assertAlmostEqual(wx * tx + wy * ty, 0.0, places=3)
        rpx, rpy = s._tilt_pivot_local()
        ax = cx + c * rpx - sn * rpy + wx
        ay = cy + sn * rpx + c * rpy + wy
        self.assertAlmostEqual(
            (ax - point[0]) * nx + (ay - point[1]) * ny, 0.0, places=3,
        )
        s.angle = 0.0

        # A stored bottom contact seats the same way. A bare angle does not.
        s.tilt = contact
        csx, csy = s._tilt_seat_local(cx, cy)
        self.assertAlmostEqual(csx, sx, places=4)
        self.assertAlmostEqual(csy, sy, places=4)
        s.tilt = 22.0
        self.assertEqual(s._tilt_seat_local(cx, cy), (0.0, 0.0))

        # (0, -1) is the same face as "bottom".
        s.hitbox.anchor = (0, -1)
        s.tilt = "ground"
        nsx, nsy = s._tilt_seat_local(cx, cy)
        self.assertAlmostEqual(nsx, sx, places=3)
        self.assertAlmostEqual(nsy, sy, places=3)

    def test_tilt_seat_is_zero_on_flat_ground_and_other_anchors(self):
        """A hull toe on flat ground does not slide the art. Other anchors stay."""
        from scena.collision import TouchingContact
        from scena import Vec2

        path = self.tmp("wide-seat.png")
        _write_rect_png(path, 80, 40)
        s = self.track(Sprite(
            path, center=(0.0, 30.0), width=80, height=40,
            hitbox_shape="hull", hitbox_anchor="bottom",
        ))
        s._ensure_auto_baked()
        cx, cy = float(s.center.x), float(s.center.y)
        px, py = s._tilt_pivot_local()
        aabb = s._local_prims_aabb()
        w = abs(float(s._hitbox_pose_wh()[0]))
        toe = (cx + aabb[2] * w, cy + py)
        flat = TouchingContact(
            other=s, side="bottom", slope_angle=0.0,
            normal=Vec2(0.0, -1.0), tangent=Vec2(1.0, 0.0), point=toe,
        )
        s._collision_set_touching(frozenset({"bottom"}), (flat,))
        s.tilt = "ground"
        sx, sy = s._tilt_seat_local(cx, cy)
        self.assertAlmostEqual(sx, 0.0, places=4)
        self.assertAlmostEqual(sy, 0.0, places=4)
        self.assertLess(px, aabb[2] * w - 1.0)

        wall = TouchingContact(
            other=s, side="left", slope_angle=90.0,
            normal=Vec2(-1.0, 0.0), tangent=Vec2(0.0, 1.0), point=(cx - 40.0, cy),
        )
        s.tilt = wall
        self.assertEqual(s._tilt_seat_local(cx, cy), (0.0, 0.0))

        for anchor in ("center", "top", "left", "right"):
            body = self.track(Sprite(
                path, center=(0.0, 30.0), width=80, height=40,
                hitbox_shape="rect", hitbox_anchor=anchor,
            ))
            body._ensure_auto_baked()
            body._collision_set_touching(frozenset({"bottom"}), (flat,))
            body.tilt = "ground"
            self.assertEqual(
                body._tilt_seat_local(float(body.center.x), float(body.center.y)),
                (0.0, 0.0),
                msg=anchor,
            )

    def test_hull_tilt_pivot_is_bottom_center(self):
        """A flat hull bottom leans about its middle, not one toe."""
        path = self.tmp("wide.png")
        _write_rect_png(path, 80, 40)
        s = self.track(Sprite(
            path, center=(0, 0), width=80, height=40,
            hitbox_shape="hull", hitbox_anchor="bottom",
        ))
        s._ensure_auto_baked()
        aabb = s._local_prims_aabb()
        w, h = s._hitbox_pose_wh()
        w, h = abs(float(w)), abs(float(h))
        px, py = s._tilt_pivot_local()
        mid_x = 0.5 * (aabb[0] + aabb[2])
        self.assertAlmostEqual(px, mid_x * w, places=3)
        self.assertAlmostEqual(py, aabb[1] * h, places=3)
        self.assertLess(px, aabb[2] * w - 1.0)

    def test_tilt_auto_ground_picks_highest_point_y(self):
        """tilt='ground' should deterministically pick one bottom contact."""
        from scena.collision import TouchingContact
        from scena import Vec2

        s = self.track(Sprite(
            self._sheet(), center=(0, 0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom",
        ))
        c_low = TouchingContact(
            other=s,
            side="bottom",
            slope_angle=10.0,
            normal=Vec2(0.0, 1.0),
            tangent=Vec2(1.0, 0.0),
            point=(0.0, 0.0),
        )
        c_high = TouchingContact(
            other=s,
            side="bottom",
            slope_angle=20.0,
            normal=Vec2(0.0, 1.0),
            tangent=Vec2(1.0, 0.0),
            point=(0.0, 5.0),
        )
        s._collision_set_touching(frozenset({"bottom"}), (c_low, c_high))
        s.tilt = "ground"
        self.assertAlmostEqual(s.tilt, 20.0)

    def test_tilt_auto_ground_clears_when_airborne(self):
        """tilt='ground' must read 0 when there is no bottom contact."""
        from scena.collision import TouchingContact
        from scena import Vec2

        s = self.track(Sprite(
            self._sheet(), center=(0, 0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom",
        ))
        grounded = TouchingContact(
            other=s,
            side="bottom",
            slope_angle=22.0,
            normal=Vec2(0.375, -0.927),
            tangent=Vec2(0.927, 0.375),
            point=(5.0, -10.0),
        )
        s._collision_set_touching(frozenset({"bottom"}), (grounded,))
        s.tilt = "ground"
        self.assertAlmostEqual(s.tilt, 22.0)
        # Leave the ground — auto mode must not stick.
        s._collision_set_touching(frozenset(), ())
        self.assertAlmostEqual(s.tilt, 0.0)
        self.assertIsNone(s._select_ground_contact())

    def test_tilt_contact_mode_sticks_until_cleared(self):
        """tilt=TouchingContact sticks; authors must tilt=0 when airborne."""
        from scena.collision import TouchingContact
        from scena import Vec2

        s = self.track(Sprite(
            self._sheet(), center=(0, 0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom",
        ))
        c = TouchingContact(
            other=s,
            side="bottom",
            slope_angle=22.0,
            normal=Vec2(0.375, -0.927),
            tangent=Vec2(0.927, 0.375),
            point=(5.0, -10.0),
        )
        s.tilt = c
        self.assertAlmostEqual(s.tilt, 22.0)
        # Contacts cleared (jump / ledge) but contact-mode state remains.
        s._collision_set_touching(frozenset(), ())
        self.assertAlmostEqual(s.tilt, 22.0)
        # Documented explicit recipe: reset before re-scanning contacts.
        s.tilt = 0
        for contact in s.touching_contacts:
            if contact.side == "bottom":
                s.tilt = contact
        self.assertAlmostEqual(s.tilt, 0.0)

    def test_tilt_reset_rotation_clears_modes(self):
        s = self.track(Sprite(
            self._sheet(), center=(0, 0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom",
        ))
        s.tilt = "ground"
        s.reset_rotation()
        self.assertEqual(s._tilt_mode, "angle")
        self.assertAlmostEqual(s.tilt, 0.0)
        from scena.collision import TouchingContact
        from scena import Vec2
        s.tilt = TouchingContact(
            other=s, side="bottom", slope_angle=15.0,
            normal=Vec2(0.0, -1.0), tangent=Vec2(1.0, 0.0), point=(0.0, 0.0),
        )
        s.reset_rotation()
        self.assertEqual(s._tilt_mode, "angle")
        self.assertAlmostEqual(s.tilt, 0.0)

    def test_play_next_switches_after_loops(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))
        s.play("hit", loops=1, next="idle")
        self.assertEqual(s.frame, 3)
        clock.advance(1.05)
        self.assertEqual(s.frame, 0)
        self.assertEqual(s._play_name, "idle")

    def test_play_is_not_cancelled_by_mode(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))

        def idle(e):
            pass

        def other(e):
            pass

        s.play("idle")
        clock.advance(0.15)
        self.assertEqual(s.frame, 1)
        s.mode = idle
        s.mode = other
        self.assertEqual(s.frame, 1)

    def test_setting_frame_stops_play(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))
        s.play("idle")
        s.frame = 3
        self.assertIsNone(s._play_name)
        clock.advance(1.0)
        self.assertEqual(s.frame, 3)

    def test_cols_strip_autoplay(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        s = self.track(Sprite(Sheet(path, cols=4, fps=8), center=(0, 0), size=16))
        self.assertEqual(s.sheet.nframes, 4)
        self.assertEqual(s._play_name, "default")
        self.assertFalse(s._play_yoyo)

    def test_cols_strip_name_and_yoyo(self):
        path = self.tmp("idle.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        s = self.track(Sprite(
            Sheet(path, cols=4, fps=10, name="idle", yoyo=True),
            center=(0, 0), size=16,
        ))
        self.assertEqual(s._play_name, "idle")
        self.assertTrue(s._play_yoyo)
        self.assertEqual(s.frame, 0)
        clock.advance(0.45)  # 4.5 frames at 10 fps → yoyo step 4 → frame 2
        self.assertEqual(s.frame, 2)

    def test_name_without_fps_raises(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        with self.assertRaises(TypeError) as ctx:
            Sheet(path, cols=4, name="walk")
        self.assertIn("fps=", str(ctx.exception))

    def test_yoyo_without_fps_raises(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        with self.assertRaises(TypeError) as ctx:
            Sheet(path, cols=4, yoyo=True)
        self.assertIn("fps=", str(ctx.exception))

    def test_fps_shortcut_then_sheet_clip_upgrade(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        s = self.track(Sprite(
            Sheet(path, cols=4, fps=8, name="walk"),
            center=(0, 0), size=16,
        ))
        self.assertEqual(s._play_name, "walk")
        s.sheet.clip("idle", [0], fps=1)
        s.play("idle")
        self.assertEqual(s._play_name, "idle")

    def test_cols_rows_layout(self):
        path = self.tmp("sheet.png")
        _write_grid_png(path, cell=16, cols=4, rows=2)
        sh = Sheet(path, cols=4, rows=2)
        self.assertEqual(sh.nframes, 8)
        self.assertEqual(sh._cell_w, 16)
        self.assertEqual(sh._cell_h, 16)

    def test_vertical_strip(self):
        path = self.tmp("vstrip.png")
        _write_grid_png(path, cell=8, cols=1, rows=4)
        s = self.track(Sprite(
            Sheet(path, cols=1, rows=4, fps=8),
            center=(0, 0), size=16,
        ))
        self.assertEqual(s.sheet.nframes, 4)
        self.assertEqual(s._play_name, "default")

    def test_rows_without_cols_raises(self):
        path = self.tmp("v.png")
        _write_grid_png(path, cell=8, cols=1, rows=4)
        with self.assertRaises(TypeError) as ctx:
            Sheet(path, rows=4)
        self.assertIn("cols=", str(ctx.exception))

    def test_cols_and_cell_rejected(self):
        with self.assertRaises(TypeError) as ctx:
            Sheet("x.png", cols=4, cell=(16, 16))
        self.assertIn("cell=", str(ctx.exception))

    def test_cols_does_not_divide_raises(self):
        path = self.tmp("odd.png")
        _write_rect_png(path, 50, 16)
        with self.assertRaises(ValueError) as ctx:
            Sheet(path, cols=4)
        self.assertIn("divide", str(ctx.exception).lower())

    def test_clip_rejects_bad_indices(self):
        sh = self._sheet()
        with self.assertRaises(ValueError) as ctx:
            sh.clip("bad", [0, 99], fps=4)
        self.assertIn("out of range", str(ctx.exception))

    def test_play_next_must_be_a_clip_name(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))

        def diving():
            pass

        with self.assertRaises(TypeError) as ctx:
            s.play("hit", loops=1, next=diving)
        self.assertIn("clip name", str(ctx.exception))

    def test_play_loops_holds_last_on_clip(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))
        s.play("idle", loops=1)
        clock.advance(0.35)  # 3.5 frames at 10 fps, period 3 → done, hold 2
        self.assertEqual(s.frame, 2)
        self.assertIsNone(s._play_name)

    def test_play_yoyo_ping_pongs(self):
        sh = self._bare_sheet()
        sh.clip("idle", [0, 1, 2], fps=10, yoyo=True)
        s = self.track(Sprite(sh, center=(0, 0), size=32))
        s.play("idle")
        self.assertEqual(s.frame, 0)
        clock.advance(0.15)  # 1.5 → 1
        self.assertEqual(s.frame, 1)
        clock.advance(0.10)  # 2.5 → 2
        self.assertEqual(s.frame, 2)
        clock.advance(0.10)  # 3.5 → 1 (turnaround, not wrap to 0)
        self.assertEqual(s.frame, 1)
        clock.advance(0.10)  # 4.5 → 0
        self.assertEqual(s.frame, 0)
        clock.advance(0.10)  # 5.5 → 1
        self.assertEqual(s.frame, 1)

    def test_play_yoyo_loops_holds_first(self):
        sh = self._bare_sheet()
        sh.clip("idle", [0, 1, 2], fps=10, yoyo=True)
        s = self.track(Sprite(sh, center=(0, 0), size=32))
        s.play("idle", loops=1)
        clock.advance(0.35)  # 3.5 → still in round trip (period 4), frame 1
        self.assertEqual(s.frame, 1)
        self.assertEqual(s._play_name, "idle")
        clock.advance(0.10)  # 4.5 → done, hold first frame
        self.assertEqual(s.frame, 0)
        self.assertIsNone(s._play_name)

    def test_play_yoyo_next_after_round_trip(self):
        sh = self._bare_sheet()
        sh.clip("idle", [0, 1, 2], fps=10, yoyo=True)
        sh.clip("hit", [3], fps=1)
        s = self.track(Sprite(sh, center=(0, 0), size=32))
        s.play("idle", loops=1, next="hit")
        clock.advance(0.45)  # period 4 → switch to hit
        self.assertEqual(s.frame, 3)
        self.assertEqual(s._play_name, "hit")

    def test_next_onto_yoyo_keeps_ping_pong(self):
        sh = self._bare_sheet()
        sh.clip("hit", [3], fps=1)
        sh.clip("idle", [0, 1, 2], fps=10, yoyo=True)
        s = self.track(Sprite(sh, center=(0, 0), size=32))
        s.play("hit", loops=1, next="idle")
        clock.advance(1.05)
        self.assertEqual(s.frame, 0)  # idle began at the 1.0 s boundary, not at this read (PB4)
        self.assertEqual(s._play_name, "idle")
        self.assertTrue(s._play_yoyo)
        clock.advance(0.30)  # 0.35 s since the boundary: 3.5 frames → yoyo frame 1
        self.assertEqual(s.frame, 1)

    def test_yoyo_overwrites_clip_same_name(self):
        sh = self._bare_sheet()
        sh.clip("idle", [0, 1, 2], fps=10)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            sh.clip("idle", [0, 1, 2], fps=10, yoyo=True)
        self.assertTrue(any("replaced" in str(w.message) for w in caught))
        s = self.track(Sprite(sh, center=(0, 0), size=32))
        s.play("idle")
        clock.advance(0.35)  # 3.5 → yoyo frame 1, not cycle wrap to 0
        self.assertEqual(s.frame, 1)

    def test_yoyo_accepts_frame_names(self):
        sh = self._bare_sheet()
        sh.clip("wobble", [0, 1, 2], fps=8, yoyo=True)
        s = self.track(Sprite(sh, center=(0, 0), size=32))
        s.play("wobble")
        self.assertTrue(s._play_yoyo)
        self.assertEqual(s.frame, 0)

    def test_yoyo_rejects_empty_frames(self):
        sh = self._bare_sheet()
        with self.assertRaises(ValueError) as ctx:
            sh.clip("idle", [], fps=6, yoyo=True)
        self.assertIn("Sheet.clip", str(ctx.exception))

    def test_strip_appends_image_and_plays(self):
        run = self.tmp("run.png")
        idle = self.tmp("idle.png")
        _write_grid_png(run, cell=8, cols=4, rows=1)
        _write_grid_png(idle, cell=8, cols=3, rows=1)
        sh = Sheet(run, cols=4, fps=8, name="walk")
        sh.strip("idle", idle, cols=3, fps=6, yoyo=True)
        s = self.track(Sprite(sh, center=(0, 0), size=16))
        self.assertEqual(s.sheet.nframes, 7)
        self.assertEqual(len(s.sheet._images), 2)
        self.assertIsNot(s.sheet._image_for_frame(0), s.sheet._image_for_frame(4))
        self.assertIsNone(s._play_name)  # two clips → still until play
        s.play("idle")
        self.assertEqual(s._play_name, "idle")
        self.assertTrue(s._play_yoyo)
        self.assertEqual(s.frame, 4)  # first frame of appended clip
        clock.advance(0.25)  # 1.5 frames at 6 fps → index 1 within clip → sheet 5
        self.assertEqual(s.frame, 5)

    def test_strip_requires_name(self):
        path = self.tmp("run.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        sh = Sheet(path, cols=4, fps=8)
        idle = self.tmp("idle.png")
        _write_grid_png(idle, cell=8, cols=2, rows=1)
        with self.assertRaises(TypeError):
            sh.strip("", idle, cols=2, fps=4)
        with self.assertRaises(TypeError) as ctx:
            sh.strip(None, idle, cols=2, fps=4)
        self.assertIn("name", str(ctx.exception).lower())

    def test_sprite_has_no_strip(self):
        path = self.tmp("run.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        s = self.track(Sprite(Sheet(path, cols=4, fps=8), center=(0, 0), size=16))
        self.assertFalse(hasattr(s, "add_clip"))
        self.assertFalse(hasattr(s, "strip"))

    def test_sheet_strip_before_sprites(self):
        run = self.tmp("run.png")
        idle = self.tmp("idle.png")
        _write_grid_png(run, cell=8, cols=4, rows=1)
        _write_grid_png(idle, cell=8, cols=2, rows=1)
        sh = Sheet(run, cols=4)
        sh.clip("walk", [0, 1, 2, 3], fps=8)
        sh.strip("idle", idle, cols=2, fps=4)
        s = self.track(Sprite(sh, center=(0, 0), size=16))
        s.play("idle")
        self.assertEqual(s.frame, 4)

    def test_empty_sheet_then_strip(self):
        idle = self.tmp("idle.png")
        _write_grid_png(idle, cell=8, cols=4, rows=1)
        sh = Sheet()
        self.assertEqual(sh.nframes, 0)
        with self.assertRaises(ValueError) as ctx:
            Sprite(sh, center=(0, 0), size=16)
        self.assertIn("empty", str(ctx.exception).lower())
        sh.strip("idle", idle, cols=4, fps=6)
        s = self.track(Sprite(sh, center=(0, 0), size=16))
        self.assertEqual(s._play_name, "idle")
        self.assertEqual(s.sheet.nframes, 4)

    def test_clip_omitted_frames_uses_all_cells(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        sh = Sheet(path, cols=4)
        sh.clip("walk", fps=8)
        self.assertEqual(sh._cycles["walk"][0], [0, 1, 2, 3])
        s = self.track(Sprite(sh, center=(0, 0), size=16))
        self.assertEqual(s._play_name, "walk")

    def test_clip_omitted_frames_on_empty_raises(self):
        sh = Sheet()
        with self.assertRaises(ValueError) as ctx:
            sh.clip("walk", fps=8)
        self.assertIn("no frames", str(ctx.exception))

    def test_frame_kwarg_wins_over_single_clip_autoplay(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        sh = Sheet(path, cols=4, fps=8)
        s = self.track(Sprite(sh, frame=2, center=(0, 0), size=16))
        self.assertIsNone(s._play_name)
        self.assertEqual(s.frame, 2)

    def test_two_clips_do_not_autoplay(self):
        sh = self._sheet()
        s = self.track(Sprite(sh, center=(0, 0), size=32))
        self.assertIsNone(s._play_name)
        self.assertEqual(s.frame, 0)

    def test_play_clip_keyword(self):
        s = self.track(Sprite(self._sheet(), center=(0, 0), size=32))
        s.play(clip="idle")
        self.assertEqual(s._play_name, "idle")

    def test_extra_positionals_with_cols_points_at_strip(self):
        a = self.tmp("a.png")
        b = self.tmp("b.png")
        _write_rect_png(a, 8, 8)
        _write_rect_png(b, 8, 8)
        with self.assertRaises(TypeError) as ctx:
            Sheet(a, b, cols=8)
        msg = str(ctx.exception)
        self.assertIn("strip", msg)

    def test_list_source_plus_extra_positionals_raises(self):
        a = self.tmp("a.png")
        b = self.tmp("b.png")
        c = self.tmp("c.png")
        _write_rect_png(a, 8, 8)
        _write_rect_png(b, 8, 8)
        _write_rect_png(c, 8, 8)
        with self.assertRaises(TypeError) as ctx:
            Sheet([a, b], c)
        self.assertIn("extra positional", str(ctx.exception))

    def test_sprite_catalog_kwargs_raise(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        with self.assertRaises(TypeError) as ctx:
            Sprite(path, cols=4, center=(0, 0), size=16)
        self.assertIn("Sheet", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            Sprite(path, fps=8, center=(0, 0), size=16)
        self.assertIn("Sheet", str(ctx.exception))

    def test_clip_overwrite_warns(self):
        sh = self._bare_sheet()
        sh.clip("idle", [0, 1], fps=4)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            sh.clip("idle", [0, 1, 2], fps=8)
        self.assertTrue(any("replaced" in str(w.message) for w in caught))


class TestHitboxAndPose(SpriteTestCase):
    def test_default_hitbox_is_auto_lazy(self):
        s = self.track(Sprite(center=(0, 0), width=100, height=40))
        self.assertEqual(s.hitbox.shape, "auto")
        self.assertEqual(s.hitbox.scale, (1.0, 1.0))
        self.assertFalse(s._auto_baked)
        # Snapshot enrolls bake (safety net); placeholder may fall back to rect.
        prims = snapshot_shape(s)
        self.assertEqual(len(prims), 1)
        self.assertTrue(s._auto_baked or s.hitbox.shape == "rect")

    def test_hitbox_auto_plus_bakes_two_ellipses(self):
        sh = Sheet(media("shooter", "sheet.xml"))   # plus-shaped Kenney laser frame
        s = self.track(Sprite(sh, frame="laserRed09.png", center=(0, 0), height=48, hitbox_shape="auto"))
        s.collidable = True
        self.assertEqual(len(s._hitbox_ellipses), 2)

    def test_hitbox_auto_shares_atlas_cache_across_sprites(self):
        """Two Sprites on the same sheet frame share one auto bake (Galaga wave)."""
        from scena.atlas import (
            _AUTO_CACHE, auto_collider_for_frame, image_cache_token, reset_atlas_caches,
        )

        sh = Sheet(media("shooter", "sheet.xml"))   # plus-shaped Kenney laser frame
        reset_atlas_caches()
        a = self.track(Sprite(sh, frame="laserRed09.png", center=(0, 0), height=48, hitbox_shape="auto"))
        a.collidable = True
        self.assertTrue(a._auto_baked)
        n_after_first = len(_AUTO_CACHE)
        self.assertGreaterEqual(n_after_first, 1)
        fr = a._sheet._frame_at(a._current_frame_index())
        from scena.atlas import _auto_key
        key = _auto_key(a._sheet.image, fr)
        first = _AUTO_CACHE[key]
        b = self.track(Sprite(sh, frame="laserRed09.png", center=(80, 0), height=48, hitbox_shape="auto"))
        b.collidable = True
        self.assertEqual(len(_AUTO_CACHE), n_after_first)
        self.assertIs(_AUTO_CACHE[key], first)
        again = auto_collider_for_frame(a._sheet.image, fr)
        self.assertIs(again, first)
        self.assertEqual(len(b._hitbox_ellipses), len(a._hitbox_ellipses))

    def test_hitbox_auto_fresh_sheet_per_spawn_reuses_bake(self):
        """``Sprite(Sheet(xml), frame=…, hitbox_shape="auto")`` per spawn fits once."""
        from scena.atlas import _AUTO_CACHE, _MASK_CACHE, reset_atlas_caches

        xml = media("shooter", "sheet.xml")
        reset_atlas_caches()
        a = self.track(Sprite(Sheet(xml), frame="meteorBrown_big1.png", size=56, hitbox_shape="auto"))
        a.collidable = True
        self.assertTrue(a._auto_baked)
        sizes = (len(_AUTO_CACHE), len(_MASK_CACHE))
        b = self.track(Sprite(Sheet(xml), frame="meteorBrown_big1.png", size=56, hitbox_shape="auto"))
        self.assertIsNot(b._sheet, a._sheet)
        b.collidable = True
        self.assertEqual((len(_AUTO_CACHE), len(_MASK_CACHE)), sizes)
        fields = ("_hitbox_boxes", "_hitbox_circle", "_hitbox_circles",
                  "_hitbox_ellipse", "_hitbox_ellipses", "_hitbox_poly")
        self.assertEqual([getattr(b, f) for f in fields], [getattr(a, f) for f in fields])

    def test_hitbox_auto_disk_prefers_circle(self):
        path = self.tmp("sq.png")
        _write_rect_png(path, 32, 32)
        s = self.track(Sprite(path, center=(0, 0), width=32, height=32, hitbox_shape="auto"))
        s.collidable = True
        # Filled square under rotation-safe policy: circle (or 1-rect / hull), never multi-rect.
        if s._hitbox_boxes:
            self.assertEqual(len(s._hitbox_boxes), 1)
        else:
            self.assertTrue(
                s._hitbox_circle is not None
                or s._hitbox_poly
                or s._hitbox_ellipse is not None
            )

    def test_hitbox_rect_is_full_sprite(self):
        s = self.track(Sprite(center=(0, 0), width=100, height=40, hitbox_shape="rect"))
        minx, miny, maxx, maxy = snapshot_shape(s)[0].aabb
        self.assertAlmostEqual(maxx - minx, 100)
        self.assertAlmostEqual(maxy - miny, 40)

    def test_hitbox_rect_on_padded_art_is_silhouette(self):
        path = self.tmp("padded.png")
        _write_padded_png(path, canvas_w=64, canvas_h=32, blob=(22, 10, 20, 12))
        s = self.track(Sprite(path, center=(0, 0), width=64, height=32, hitbox_shape="rect"))
        minx, miny, maxx, maxy = snapshot_shape(s)[0].aabb
        self.assertLess(maxx - minx, 64.0 - 1e-3)
        self.assertLess(maxy - miny, 32.0 - 1e-3)
        self.assertGreater(maxx - minx, 10.0)
        self.assertGreater(maxy - miny, 6.0)

    def test_hitbox_rect_ninja_recall_is_one(self):
        path = media("ninja", "Idle__000.png")
        from scena.atlas import _mask_for_region, auto_collider_for_frame

        s = self.track(Sprite(path, center=(0, 0), height=70, hitbox_shape="rect"))
        prim = snapshot_shape(s)[0]
        sheet = s.sheet
        fr = sheet._frame_at(0)
        col = auto_collider_for_frame(sheet._image_for_frame(0), fr, force_kind="bbox")
        self.assertAlmostEqual(col.recall, 1.0)
        mask = _mask_for_region(sheet._image_for_frame(0), fr.x, fr.y, fr.w, fr.h)
        mh, mw = mask.shape
        du_w, du_h = abs(float(s.width)), abs(float(s.height))
        minx, miny, maxx, maxy = prim.aabb
        ys, xs = __import__("numpy").nonzero(mask)
        for y, x in zip(ys.tolist(), xs.tolist()):
            nx = ((x + 0.5) / mw) - 0.5
            ny = 0.5 - ((y + 0.5) / mh)
            wx, wy = nx * du_w, ny * du_h
            self.assertGreaterEqual(wx, minx - 1e-3)
            self.assertLessEqual(wx, maxx + 1e-3)
            self.assertGreaterEqual(wy, miny - 1e-3)
            self.assertLessEqual(wy, maxy + 1e-3)

    def test_hitbox_circle_and_hull_bake(self):
        disk = self.tmp("disk.png")
        _write_disk_png(disk, side=64, radius=28)
        circ = self.track(Sprite(disk, center=(0, 0), width=64, height=64, hitbox_shape="circle"))
        snapshot_shape(circ)
        self.assertEqual(circ.hitbox.shape, "circle")
        self.assertIsNotNone(circ._hitbox_circle)
        self.assertEqual(snapshot_shape(circ)[0].kind, PrimKind.CIRCLE)

        path = self.tmp("ell.png")
        _write_l_png(path, 32)
        hull = self.track(Sprite(path, center=(80, 0), width=32, height=32, hitbox_shape="hull"))
        snapshot_shape(hull)
        self.assertEqual(hull.hitbox.shape, "hull")
        self.assertGreaterEqual(len(hull._hitbox_poly), 3)
        self.assertEqual(snapshot_shape(hull)[0].kind, PrimKind.POLY)

    def test_atlas_cells_draw_at_their_own_size(self):
        """``height=`` fixes one scale on the construct cell; a bigger cell draws bigger.

        Contract since "one scale per sprite" (Sprite Design — Scale and
        registration). The frozen body collider stays on the construct cell.
        """
        png = self.tmp("mix.png")
        info = skia.ImageInfo.Make(24, 16, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        c = surf.getCanvas()
        c.drawRect(skia.Rect.MakeXYWH(0, 0, 8, 8), skia.Paint(Color=skia.ColorWHITE))
        c.drawRect(skia.Rect.MakeXYWH(8, 0, 16, 16), skia.Paint(Color=skia.ColorWHITE))
        surf.makeImageSnapshot().save(png, skia.kPNG)
        atlas = self.tmp("mix.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {"image": os.path.basename(png)},
                "frames": {
                    "small": {"frame": {"x": 0, "y": 0, "w": 8, "h": 8}},
                    "big": {"frame": {"x": 8, "y": 0, "w": 16, "h": 16}},
                },
            }, f)
        sheet = Sheet(png, atlas=atlas)
        s = self.track(Sprite(
            sheet, frame="small", center=(0, 0), height=8, hitbox_shape="rect",
        ))
        minx, miny, maxx, maxy = snapshot_shape(s)[0].aabb
        self.assertAlmostEqual(maxx - minx, 8.0, places=3)
        self.assertAlmostEqual(maxy - miny, 8.0, places=3)
        s.frame = "big"
        self.assertAlmostEqual(float(s.height), 16.0, places=3)
        minx, miny, maxx, maxy = snapshot_shape(s)[0].aabb
        self.assertAlmostEqual(maxx - minx, 8.0, places=3)
        self.assertAlmostEqual(maxy - miny, 8.0, places=3)
        cx, cy, w, h, _ang = s._oriented_frame()
        self.assertAlmostEqual(w, 16.0, places=3)
        self.assertAlmostEqual(h, 16.0, places=3)

    def test_atlas_play_keeps_the_scale_for_the_clip_cell(self):
        """``play()`` draws the clip cell at the sprite's one scale (2 du/px here)."""
        png = self.tmp("aspect.png")
        info = skia.ImageInfo.Make(16, 16, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        c = surf.getCanvas()
        c.drawRect(skia.Rect.MakeXYWH(0, 0, 8, 8), skia.Paint(Color=skia.ColorWHITE))
        c.drawRect(skia.Rect.MakeXYWH(8, 0, 8, 16), skia.Paint(Color=skia.ColorWHITE))
        surf.makeImageSnapshot().save(png, skia.kPNG)
        atlas = self.tmp("aspect.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {"image": os.path.basename(png)},
                "frames": {
                    "small": {"frame": {"x": 0, "y": 0, "w": 8, "h": 8}},
                    "tall": {"frame": {"x": 8, "y": 0, "w": 8, "h": 16}},
                },
            }, f)
        sheet = Sheet(png, atlas=atlas)
        sheet.clip("tall", ["tall"], fps=1)
        s = self.track(Sprite(sheet, frame="small", center=(0, 0), height=16, hitbox_shape="rect"))
        self.assertAlmostEqual(float(s.height), 16.0, places=3)
        self.assertAlmostEqual(float(s.width), 16.0, places=3)
        s.play("tall")
        self.assertAlmostEqual(float(s.height), 32.0, places=3)
        self.assertAlmostEqual(float(s.width), 16.0, places=3)
        # Drawn box follows the clip; the frozen rect stays on the construct cell.
        minx, miny, maxx, maxy = snapshot_shape(s)[0].aabb
        self.assertAlmostEqual(maxx - minx, 16.0, places=3)
        self.assertAlmostEqual(maxy - miny, 16.0, places=3)
        _cx, _cy, w, h, _ang = s._oriented_frame()
        self.assertAlmostEqual(w, 16.0, places=3)
        self.assertAlmostEqual(h, 32.0, places=3)

    def test_hitbox_scale_shrinks_collider_not_draw_size(self):
        a = self.track(Sprite(
            center=(0, 0), width=100, height=100, hitbox_shape="rect", hitbox_scale=0.5, group="a",
        ))
        b = self.track(Sprite(
            center=(60, 0), width=100, height=100, hitbox_shape="rect", hitbox_scale=0.5, group="b",
        ))
        # Visual half-extents 50+50 > 60 → overlap. Hitbox half 25+25=50 < 60 → miss.
        self.assertTrue(a.contains_point(40, 0))
        hits = []

        @collide("a", "b")
        def on_hit(me, other, info):
            hits.append(1)

        get_collision_system().step()
        self.assertEqual(hits, [])
        b.move_to(40, 0)
        get_collision_system().step()
        self.assertEqual(hits, [1])

    def test_numeric_hitbox_rejected(self):
        with self.assertRaises(TypeError) as ctx:
            Sprite(center=(0, 0), hitbox_shape=0.9)
        self.assertIn("hitbox_scale", str(ctx.exception))

    def test_rotated_sprite_is_obb(self):
        s = self.track(Sprite(center=(0, 0), width=80, height=20, hitbox_shape="rect"))
        s.rotate_to(90)
        prims = snapshot_shape(s)
        self.assertEqual(prims[0].kind, PrimKind.OBB)
        self.assertTrue(s.contains_point(0, 30))
        self.assertFalse(s.contains_point(30, 0))

    def test_hitbox_ellipse_misses_aabb_corner(self):
        path = self.tmp("wide.png")
        _write_rect_png(path, 100, 40)
        s = self.track(Sprite(path, center=(0, 0), width=100, height=40, hitbox_shape="ellipse"))
        prims = snapshot_shape(s)
        self.assertEqual(len(prims), 1)
        self.assertEqual(prims[0].kind, PrimKind.ELLIPSE)
        self.assertEqual(s.hitbox.shape, "ellipse")
        # AABB corner (~50, ~20) is outside the ellipse; the centre is inside.
        self.assertFalse(_prim_contains_point(prims[0], 50.0, 20.0))
        self.assertTrue(_prim_contains_point(prims[0], 0.0, 0.0))
        a = self.track(Sprite(path, center=(0, 0), width=100, height=40, hitbox_shape="ellipse", group="a"))
        corner = self.track(Circle(center=(50, 20), radius=2, group="b"))
        hits = []

        @collide("a", "b")
        def on_hit(me, other, info):
            hits.append(1)

        get_collision_system().step()
        self.assertEqual(hits, [])
        corner.move_to(0, 0)
        get_collision_system().step()
        self.assertEqual(hits, [1])

    def test_hitbox_ellipse_square_demotes_to_circle(self):
        sq = self.tmp("sq.png")
        _write_rect_png(sq, 64, 64)
        s = self.track(Sprite(sq, center=(0, 0), width=64, height=64, hitbox_shape="ellipse"))
        prims = snapshot_shape(s)
        self.assertEqual(prims[0].kind, PrimKind.CIRCLE)
        wide_path = self.tmp("wide.png")
        _write_rect_png(wide_path, 100, 40)
        wide = self.track(Sprite(wide_path, center=(100, 0), width=100, height=40, hitbox_shape="ellipse"))
        self.assertEqual(snapshot_shape(wide)[0].kind, PrimKind.ELLIPSE)

    def test_hitbox_ellipse_scale_expands(self):
        path = self.tmp("wide.png")
        _write_rect_png(path, 100, 40)
        s = self.track(Sprite(
            path, center=(0, 0), width=100, height=40, hitbox_shape="ellipse", hitbox_scale=1.2,
        ))
        prim = snapshot_shape(s)[0]
        self.assertEqual(prim.kind, PrimKind.ELLIPSE)
        # params: (cx, cy, rx, ry, ang)
        self.assertAlmostEqual(prim.params[2], 60.0, places=3)
        self.assertAlmostEqual(prim.params[3], 24.0, places=3)

    def test_hitbox_ellipse_on_padded_art_is_silhouette(self):
        path = self.tmp("padded.png")
        _write_padded_png(path, canvas_w=64, canvas_h=32, blob=(22, 10, 20, 12))
        s = self.track(Sprite(path, center=(0, 0), width=64, height=32, hitbox_shape="ellipse"))
        prim = snapshot_shape(s)[0]
        self.assertIn(prim.kind, (PrimKind.ELLIPSE, PrimKind.CIRCLE))
        minx, miny, maxx, maxy = prim.aabb
        self.assertLess(maxx - minx, 64.0 - 1e-3)
        self.assertLess(maxy - miny, 32.0 - 1e-3)

    def test_hitbox_auto_l_shape_never_multi_rect(self):
        path = self.tmp("ell.png")
        _write_l_png(path, 32)
        s = self.track(Sprite(path, center=(0, 0), width=32, height=32, hitbox_shape="auto"))
        self.assertEqual(s.hitbox.shape, "auto")
        s.collidable = True
        # Rotation-safe auto: never multi-rect (would become multi-OBB).
        if s._hitbox_boxes:
            self.assertEqual(len(s._hitbox_boxes), 1)
        else:
            self.assertTrue(
                s._hitbox_circle is not None
                or s._hitbox_circles
                or s._hitbox_poly
                or s._hitbox_ellipse is not None
                or s._hitbox_ellipses
            )
        # Explicit rect hitbox stays available for cheap axis-aligned tiles.
        tile = self.track(Sprite(path, center=(80, 0), width=32, height=32, hitbox_shape="rect"))
        self.assertEqual(tile.hitbox.shape, "rect")

    def test_hitbox_auto_picks_circle_for_disk(self):
        path = self.tmp("disk.png")
        _write_disk_png(path, side=64, radius=28)
        s = self.track(Sprite(path, center=(0, 0), width=64, height=64, hitbox_shape="auto"))
        self.assertEqual(s.hitbox.shape, "auto")
        snapshot_shape(s)  # bake
        self.assertIsNotNone(s._hitbox_circle)
        prims = snapshot_shape(s)
        self.assertEqual(len(prims), 1)
        self.assertEqual(prims[0].kind, PrimKind.CIRCLE)
        # AABB corner of the 64×64 rect is outside the disk.
        self.assertFalse(_prim_contains_point(prims[0], 32.0, 32.0))
        self.assertTrue(_prim_contains_point(prims[0], 0.0, 0.0))

    def test_hitbox_auto_meteor_is_round_ship_is_not(self):
        png = media("shooter", "sheet.png")
        xml = media("shooter", "sheet.xml")
        sh = Sheet(png, atlas=xml)
        meteor = self.track(Sprite(
            sh, frame="meteorGrey_big1.png", center=(0, 0), size=64, hitbox_shape="auto",
        ))
        snapshot_shape(meteor)
        # A rock silhouette isn't a perfect circle; the precision-weighted
        # policy may prefer a same-cost-ballpark hull that fits it exactly
        # (precision 1.0) over a capped-precision circle. Either is a
        # single, cheap, high-quality primitive — that's what matters here.
        self.assertTrue(
            meteor._hitbox_circle is not None
            or meteor._hitbox_circles
            or meteor._hitbox_poly
        )
        self.assertIn(
            snapshot_shape(meteor)[0].kind,
            (PrimKind.CIRCLE, PrimKind.POLY),
        )
        ship = self.track(Sprite(
            sh, frame="playerShip1_blue.png", center=(0, 0), height=48, hitbox_shape="auto",
        ))
        snapshot_shape(ship)
        # Auto never multi-rect. Circle / ellipse / hull / multi-circle / 1-rect OK.
        self.assertTrue(
            ship._hitbox_circle is not None
            or ship._hitbox_circles
            or ship._hitbox_poly
            or ship._hitbox_ellipse is not None
            or ship._hitbox_ellipses
            or ship._hitbox_boxes
        )
        if ship._hitbox_boxes:
            self.assertEqual(len(ship._hitbox_boxes), 1)
        if ship._hitbox_circles:
            self.assertLessEqual(len(ship._hitbox_circles), 5)
        if ship._hitbox_ellipses:
            self.assertLessEqual(len(ship._hitbox_ellipses), 2)
        if ship._hitbox_poly:
            self.assertGreaterEqual(len(ship._hitbox_poly), 3)
            self.assertEqual(snapshot_shape(ship)[0].kind, PrimKind.POLY)

    def test_hitbox_auto_is_baked_not_per_frame(self):
        path = self.tmp("hero.png")
        _write_blob_strip(path, cell=16)
        s = self.track(Sprite(Sheet(path, cols=4, fps=8), center=(0, 0), size=32, hitbox_shape="auto"))
        s.collidable = True
        fingerprint = s._collision_specs()
        frame0 = int(s._hitbox_frame)
        self.assertEqual(frame0, 0)
        for _ in range(8):
            clock.advance(0.125)
            self.assertEqual(s._collision_specs(), fingerprint)
            self.assertEqual(s._hitbox_frame, frame0)

    def test_atlas_json_named_frame_and_pivot(self):
        png = self.tmp("sheet.png")
        _write_grid_png(png, cell=16, cols=2, rows=1)
        atlas = self.tmp("sheet.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {"image": os.path.basename(png)},
                "frames": {
                    "left": {
                        "frame": {"x": 0, "y": 0, "w": 16, "h": 16},
                        "pivot": {"x": 0.0, "y": 0.5},
                    },
                    "right": {
                        "frame": {"x": 16, "y": 0, "w": 16, "h": 16},
                        "pivot": {"x": 1.0, "y": 0.5},
                    },
                },
            }, f)
        sheet = Sheet(png, atlas=atlas)
        self.assertEqual(sheet.nframes, 2)
        self.assertIn("left", sheet.names)
        s = self.track(Sprite(sheet, frame="left", center=(0, 0), width=16, height=16, hitbox_shape="rect"))
        self.assertEqual(s.frame, 0)
        cx, cy, w, h, _ = s._oriented_frame()
        # Pivot at left edge → visual centre is +8 in x.
        self.assertAlmostEqual(cx, 8.0, places=4)
        self.assertAlmostEqual(cy, 0.0, places=4)
        s.frame = "right"
        cx2, _, _, _, _ = s._oriented_frame()
        self.assertAlmostEqual(cx2, -8.0, places=4)

    def test_atlas_json_array_and_boxes(self):
        png = self.tmp("a.png")
        _write_rect_png(png, 32, 16)
        atlas = self.tmp("a.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "frames": [{
                    "filename": "shipOn",
                    "frame": {"x": 0, "y": 0, "w": 32, "h": 16},
                    "hitboxes": [{"x": 2, "y": 2, "w": 12, "h": 12}],
                }],
            }, f)
        s = self.track(Sprite(Sheet(png, atlas=atlas), frame="shipOn", center=(0, 0), width=32, height=16))
        self.assertEqual(s.hitbox.shape, "auto")
        prims = snapshot_shape(s)
        self.assertEqual(len(prims), 1)
        minx, miny, maxx, maxy = prims[0].aabb
        self.assertAlmostEqual(maxx - minx, 12.0, places=3)
        self.assertAlmostEqual(maxy - miny, 12.0, places=3)

    def test_atlas_unknown_frame_warns_and_stays_an_actor(self):
        png = self.tmp("s.png")
        _write_rect_png(png, 8, 8)
        atlas = self.tmp("s.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({"frames": {"shipOn": {"x": 0, "y": 0, "w": 8, "h": 8}}}, f)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s = self.track(Sprite(Sheet(png, atlas=atlas), frame="nope", center=(0, 0), group="miss"))
        msgs = [w for w in caught if "Unknown frame" in str(w.message)]
        self.assertEqual(len(msgs), 1)
        self.assertIn("shipOn", str(msgs[0].message))
        self.assertTrue(s._placeholder)
        self.assertTrue(s.is_alive)
        self.assertIn(s, group["miss"])
        info = skia.ImageInfo.Make(8, 8, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        s._blit_plain(surf.getCanvas())

    def test_atlas_missing_file_warns_and_stays_legal(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            sh = Sheet("hero.png", atlas="definitely_missing_atlas.json")
            s = self.track(Sprite(sh, frame="shipOn", center=(0, 0), size=24, group="missxml"))
        msgs = [w for w in caught if "not found" in str(w.message).lower()]
        self.assertGreaterEqual(len(msgs), 1)
        self.assertTrue(sh._placeholder)
        self.assertTrue(getattr(sh, "_missing_atlas", False))
        self.assertTrue(s._placeholder)
        self.assertTrue(s.is_alive)
        self.assertEqual(len(group["missxml"]), 1)
        info = skia.ImageInfo.Make(8, 8, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        s._blit_plain(surf.getCanvas())

    def test_atlas_filename_on_sprite_raises(self):
        with self.assertRaises(TypeError) as ctx:
            Sprite("no_such_sheet.xml", frame="laser.png", center=(0, 0), height=20)
        self.assertIn("Sheet", str(ctx.exception))

    def test_unknown_ctor_kwargs_raise(self):
        with self.assertRaises(TypeError) as ctx:
            Sprite(center=(0, 0), radius=5)
        msg = str(ctx.exception)
        self.assertIn("radius", msg)
        self.assertIn("Circle", msg)
        self.assertEqual(len(group["nope"]), 0)

        with self.assertRaises(TypeError) as ctx:
            Sprite(center=(0, 0), aaa=1, group="nope")
        self.assertIn("aaa", str(ctx.exception))
        self.assertEqual(len(group["nope"]), 0)

    def test_atlas_and_cell_rejected(self):
        with self.assertRaises(TypeError) as ctx:
            Sheet("x.png", cell=(16, 16), atlas="x.json")
        self.assertIn("atlas=", str(ctx.exception))

    def test_atlas_and_cols_rejected(self):
        with self.assertRaises(TypeError) as ctx:
            Sheet("x.png", cols=4, atlas="x.json")
        self.assertIn("atlas=", str(ctx.exception))

    def test_fps_on_packed_atlas_raises(self):
        png = self.tmp("s.png")
        _write_grid_png(png, cell=8, cols=2, rows=1)
        atlas = self.tmp("s.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "frames": {
                    "a": {"x": 0, "y": 0, "w": 8, "h": 8},
                    "b": {"x": 8, "y": 0, "w": 8, "h": 8},
                }
            }, f)
        with self.assertRaises(TypeError) as ctx:
            Sheet(png, atlas=atlas, fps=8)
        self.assertIn("atlas", str(ctx.exception).lower())

    def test_atlas_source_miss_falls_back_to_listed(self):
        png = self.tmp("listed.png")
        _write_grid_png(png, cell=8, cols=2, rows=1)
        atlas = self.tmp("a.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {"image": "listed.png"},
                "frames": {
                    "a": {"x": 0, "y": 0, "w": 8, "h": 8},
                    "b": {"x": 8, "y": 0, "w": 8, "h": 8},
                },
            }, f)
        missing = self.tmp("missing.png")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            sh = Sheet(missing, atlas=atlas)
        msgs = [str(w.message) for w in caught]
        self.assertTrue(any("not found" in m.lower() for m in msgs))
        self.assertTrue(any("falling back" in m.lower() or "listed" in m.lower() for m in msgs))
        self.assertEqual(sh.nframes, 2)

    def test_atlas_source_mismatch_warns_once_and_keeps_author(self):
        author = self.tmp("author.png")
        listed = self.tmp("listed.png")
        _write_rect_png(author, 16, 8, skia.ColorRED)
        _write_rect_png(listed, 16, 8, skia.ColorBLUE)
        atlas = self.tmp("a.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {"image": "listed.png"},
                "frames": {
                    "a": {"x": 0, "y": 0, "w": 8, "h": 8},
                    "b": {"x": 8, "y": 0, "w": 8, "h": 8},
                },
            }, f)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            sh = Sheet(author, atlas=atlas)
            Sheet(author, atlas=atlas)
        mismatch = [w for w in caught if "using source" in str(w.message).lower()]
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(sh.nframes, 2)

    def test_clip_accepts_frame_names(self):
        png = self.tmp("s.png")
        _write_grid_png(png, cell=8, cols=2, rows=1)
        atlas = self.tmp("s.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "frames": {
                    "a": {"x": 0, "y": 0, "w": 8, "h": 8},
                    "b": {"x": 8, "y": 0, "w": 8, "h": 8},
                }
            }, f)
        sh = Sheet(png, atlas=atlas)
        sh.clip("flash", ["a", "b"], fps=10)
        s = self.track(Sprite(sh, center=(0, 0), size=16))
        s.play("flash")
        self.assertEqual(s.frame, 0)
        clock.advance(0.15)
        self.assertEqual(s.frame, 1)

    def test_multi_file_sheet(self):
        a = self.tmp("f1.png")
        b = self.tmp("f2.png")
        _write_rect_png(a, 8, 8, skia.ColorRED)
        _write_rect_png(b, 8, 8, skia.ColorBLUE)
        sh = Sheet([a, b])
        self.assertEqual(sh.nframes, 2)
        sh = Sheet([a, b], fps=10)
        s = self.track(Sprite(sh, center=(0, 0), size=16))
        self.assertEqual(s._play_name, "default")
        self.assertEqual(s.frame, 0)
        clock.advance(0.15)
        self.assertEqual(s.frame, 1)

    def test_clip_accepts_same_file_list(self):
        """``clip(name, files)`` can reuse the paths passed to ``Sheet``."""
        idle = [self.tmp("Idle__000.png"), self.tmp("Idle__001.png")]
        run = [self.tmp("Run__000.png"), self.tmp("Run__001.png")]
        for path in idle + run:
            _write_rect_png(path, 8, 8)
        sh = Sheet(idle + run)
        sh.clip("parado", idle, fps=10)
        sh.clip("correndo", run, fps=10)
        s = self.track(Sprite(sh, center=(0, 0), size=16))
        s.play("parado")
        self.assertEqual(s.frame, 0)
        clock.advance(0.15)
        self.assertEqual(s.frame, 1)
        s.play("correndo")
        self.assertEqual(s.frame, 2)

    def test_multi_file_positional(self):
        a = self.tmp("p1.png")
        b = self.tmp("p2.png")
        _write_rect_png(a, 4, 4)
        _write_rect_png(b, 4, 4)
        s = self.track(Sprite(Sheet(a, b, fps=8), center=(0, 0), size=8))
        self.assertEqual(s.sheet.nframes, 2)

    def test_cell_as_columns_raises_with_hint(self):
        path = self.tmp("wide.png")
        _write_rect_png(path, 800, 64)
        with self.assertRaises(ValueError) as ctx:
            Sheet(path, cell=(8, 1))
        msg = str(ctx.exception)
        self.assertIn("cols=", msg)
        self.assertIn("cell=", msg)

    def test_kenney_xml_space_sheet(self):
        png = media("shooter", "sheet.png")
        xml = media("shooter", "sheet.xml")
        sh = Sheet(png, atlas=xml)
        self.assertGreater(sh.nframes, 10)
        s = self.track(Sprite(sh, frame="playerShip1_blue.png", center=(0, 0), height=48))
        self.assertEqual(sh.names[s.frame], "playerShip1_blue.png")
        self.assertAlmostEqual(float(s.height), 48)
        # Stem without extension also resolves.
        s.frame = "ufoGreen"
        self.assertIn("ufoGreen", sh.names[s.frame])

    def test_space_sheet_enemy_honors_height(self):
        """Galaga wasp path: ``height=`` on the enemy cell; same-size cells match it.

        The Kenney space atlas is drawn at one pixel scale, so a laser cell of
        the same sprite keeps its true size next to the ship.
        """
        png = media("shooter", "sheet.png")
        xml = media("shooter", "sheet.xml")
        sh = Sheet(png, atlas=xml)
        s = self.track(Sprite(
            sh, frame="enemyGreen1.png", center=(0, 0), height=58, hitbox_shape="rect",
        ))
        s.frame = "enemyRed1.png"                     # same 93×84 cell
        self.assertAlmostEqual(float(s.height), 58.0, places=3)
        fr = s._current_cell()
        expected_w = 58.0 * float(fr.src_w) / float(fr.src_h)
        self.assertAlmostEqual(float(s.width), expected_w, places=3)
        _cx, _cy, w, h, _ang = s._oriented_frame()
        self.assertAlmostEqual(h, 58.0, places=3)
        self.assertAlmostEqual(w, expected_w, places=3)
        s.frame = "laserGreen02.png"                  # 13×57 at the same scale
        self.assertAlmostEqual(float(s.height), 57.0 * 58.0 / 84.0, places=3)

    def test_xml_as_source_finds_sibling_png(self):
        xml = media("shooter", "sheet.xml")
        sh = Sheet(xml)
        self.assertFalse(sh._placeholder)
        self.assertGreater(sh.nframes, 10)

    def test_malformed_atlas_json_names_the_file(self):
        atlas = self.tmp("bad.json")
        with open(atlas, "w", encoding="utf-8") as f:
            f.write("{not json")
        with self.assertRaises(ValueError) as ctx:
            Sheet(atlas)
        self.assertIn("JSON", str(ctx.exception))

    def test_move_to_and_tween_center(self):
        s = self.track(Sprite(center=(0, 0), size=20))
        s.move_to(100, 50)
        self.assertEqual(float(s.center.x), 100)
        self.assertEqual(float(s.center.y), 50)
        tween(s.center, (200, 50), time=0.2)
        _frame(0.2)
        self.assertAlmostEqual(float(s.center.x), 200, places=4)

    def test_move_to_about_center_and_offset(self):
        s = self.track(Sprite(center=(0, 0), size=20))
        s.move_to(30, 40, about=s.center)
        self.assertAlmostEqual(float(s.center.x), 30.0, places=5)
        self.assertAlmostEqual(float(s.center.y), 40.0, places=5)
        s2 = self.track(Sprite(center=(0, 0), size=20))
        s2.move_to(30, 40, about=(-10, 0))
        self.assertAlmostEqual(float(s2.center.x), 40.0, places=5)
        self.assertAlmostEqual(float(s2.center.y), 40.0, places=5)

    def test_move_by_polar(self):
        s = self.track(Sprite(center=(0, 0), size=20))
        s.move_by(angle=90, distance=40)
        self.assertAlmostEqual(float(s.center.x), 0.0, places=5)
        self.assertAlmostEqual(float(s.center.y), 40.0, places=5)

    def test_destroy_cancels_sprite_timer(self):
        s = self.track(Sprite(center=(0, 0), size=20))
        n = []
        s.after(0.1, lambda: n.append(1))
        s.destroy()
        _frame(0.2)
        self.assertEqual(n, [])

    def test_ink_and_mode_on_sprite(self):
        s = self.track(Sprite(center=(0, 0), size=20))
        s.hp = 2

        def dying(e):
            e.hp = 0

        s.mode = dying
        self.assertEqual(float(s.hp), 0)
        self.assertEqual(s.mode, dying)

    def test_visual_body_replace_raises(self):
        s = self.track(Sprite(center=(0, 0), size=20))
        with self.assertRaises(TypeError) as ctx:
            s.visual = "not-a-look"
        self.assertIn("Sprite.visual", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            s.visual = Neon()
        self.assertIn("Sprite.visual", str(ctx.exception))
        # Flame is allowed (silhouette body); still assignable
        s.visual = Flame()
        self.assertIsInstance(s.visual, Flame)

    def test_cell_on_sprite_with_sheet_raises(self):
        path = self.tmp("g.png")
        _write_grid_png(path)
        sh = Sheet(path, cell=(16, 16))
        with self.assertRaises(TypeError) as ctx:
            Sprite(sh, cell=(16, 16), center=(0, 0))
        self.assertIn("Sheet", str(ctx.exception))

    def test_cols_on_sprite_with_sheet_raises(self):
        path = self.tmp("g.png")
        _write_grid_png(path)
        sh = Sheet(path, cols=2, rows=2)
        with self.assertRaises(TypeError) as ctx:
            Sprite(sh, cols=2, center=(0, 0))
        self.assertIn("Sheet", str(ctx.exception))

    def test_layout_with_multi_file_raises(self):
        a = self.tmp("a.png")
        b = self.tmp("b.png")
        _write_rect_png(a, 8, 8)
        _write_rect_png(b, 8, 8)
        with self.assertRaises(TypeError) as ctx:
            Sheet([a, b], cols=2)
        self.assertIn("strip", str(ctx.exception))

    def test_unknown_hitbox_string_lists_choices(self):
        with self.assertRaises(ValueError) as ctx:
            Sprite(center=(0, 0), hitbox_shape="potato")
        msg = str(ctx.exception)
        for kind in ("auto", "rect", "ellipse", "circle", "hull"):
            self.assertIn(kind, msg)


class TestHitboxFrom(SpriteTestCase):
    """Phase 1: frozen reference-set bake, ``hitbox_from``, union."""

    def _blob_sprite(self, **kwargs):
        path = self.tmp("blobs.png")
        _write_blob_strip(path, cell=32)
        kw = dict(center=(0, 0), size=32, hitbox_shape="auto")
        kw.update(kwargs)
        cols = kw.pop("cols", 4)
        fps = kw.pop("fps", 8)
        return self.track(Sprite(Sheet(path, cols=cols, fps=fps), **kw))

    def test_hitbox_from_defaults_to_construct_frame(self):
        path = self.tmp("blobs.png")
        _write_blob_strip(path, cell=32)
        s = self.track(Sprite(Sheet(path, cols=4), frame=2, center=(0, 0), size=32))
        self.assertEqual(s.hitbox.source, 2)
        self.assertEqual(s._construct_frame, 2)

    def test_hitbox_from_accepts_index_name_clip_all_each(self):
        png = self.tmp("named.png")
        _write_blob_strip(png, cell=16)
        atlas = self.tmp("named.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {"image": os.path.basename(png)},
                "frames": {
                    "idle0": {"frame": {"x": 0, "y": 0, "w": 16, "h": 16}},
                    "idle1": {"frame": {"x": 16, "y": 0, "w": 16, "h": 16}},
                    "run0": {"frame": {"x": 32, "y": 0, "w": 16, "h": 16}},
                    "run1": {"frame": {"x": 48, "y": 0, "w": 16, "h": 16}},
                },
            }, f)
        sheet = Sheet(png, atlas=atlas)
        sheet.clip("walk", ["idle0", "idle1"], fps=8)
        s = self.track(Sprite(sheet, frame="idle0", center=(0, 0), size=16, hitbox_shape="auto"))
        s.hitbox.source = 3
        self.assertEqual(s.hitbox.source, 3)
        s.hitbox.source = "run0"
        self.assertEqual(s.hitbox.source, sheet.frame_index("run0"))
        s.hitbox.source = "walk"
        self.assertEqual(s.hitbox.source, "walk")
        s.hitbox.source = "all"
        self.assertEqual(s.hitbox.source, "all")
        s.hitbox.source = "each"
        self.assertEqual(s.hitbox.source, "each")
        s.hitbox.source = "ALL"
        self.assertEqual(s.hitbox.source, "all")

    def test_hitbox_from_rejects_junk(self):
        s = self._blob_sprite()
        with self.assertRaises(ValueError):
            s.hitbox.source = "potato"
        with self.assertRaises(ValueError):
            s.hitbox.source = ""
        with self.assertRaises(TypeError):
            s.hitbox.source = True
        with self.assertRaises(TypeError):
            s.hitbox.source = 1.5

    def test_frozen_extents_are_bit_identical_across_clip_cycle(self):
        s = self._blob_sprite()
        s.collidable = True
        fingerprint = s._collision_specs()
        seen_playhead = {int(s.frame)}
        for _ in range(8):
            clock.advance(0.125)
            seen_playhead.add(int(s.frame))
            self.assertEqual(s._collision_specs(), fingerprint)
        self.assertGreater(len(seen_playhead), 1)

    def test_each_restores_per_frame_extents(self):
        s = self._blob_sprite(hitbox_source="each")
        s.collidable = True
        fingerprints = []
        for _ in range(8):
            fingerprints.append(s._collision_specs())
            clock.advance(0.125)
        unique = {repr(fp) for fp in fingerprints}
        self.assertGreater(len(unique), 1)

    def test_runtime_hitbox_from_write_rebakes(self):
        s = self._blob_sprite()
        s.collidable = True
        fp0 = s._collision_specs()
        s.hitbox.source = "all"
        fp_all = s._collision_specs()
        self.assertNotEqual(fp0, fp_all)
        s.hitbox.source = 0
        self.assertEqual(s._collision_specs(), fp0)

    def test_authored_boxes_multi_frame_uses_first_of_set(self):
        png = self.tmp("boxes.png")
        _write_blob_strip(png, cell=16)
        atlas = self.tmp("boxes.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "frames": [
                    {
                        "filename": "a",
                        "frame": {"x": 0, "y": 0, "w": 16, "h": 16},
                        "hitboxes": [{"x": 1, "y": 1, "w": 4, "h": 4}],
                    },
                    {
                        "filename": "b",
                        "frame": {"x": 16, "y": 0, "w": 16, "h": 16},
                        "hitboxes": [{"x": 0, "y": 0, "w": 16, "h": 16}],
                    },
                ],
            }, f)
        s = self.track(Sprite(
            Sheet(png, atlas=atlas), center=(0, 0), width=16, height=16,
            hitbox_source="all",
        ))
        prims = snapshot_shape(s)
        self.assertEqual(len(prims), 1)
        minx, miny, maxx, maxy = prims[0].aabb
        self.assertAlmostEqual(maxx - minx, 4.0, places=3)
        self.assertAlmostEqual(maxy - miny, 4.0, places=3)

    def test_galaga_frozen_fewer_epoch_bumps_same_contacts(self):
        """Animated fleet: freeze skips per-tick rebake; overlaps still fire."""
        from scena.collision import STATIC

        path = self.tmp("fleet.png")
        _write_blob_strip(path, cell=32)
        hits = []

        @collide("ship", "wall")
        def on_hit(me, other, info):
            hits.append(id(me))

        wall = self.track(Rect(center=(80, 0), width=200, height=48, group="wall"))
        wall.collidable = True
        wall.mass = STATIC

        def _fleet(hitbox_source=None):
            ships = []
            for i in range(6):
                kw = dict(
                    center=(i * 28, 0), size=32,
                    hitbox_shape="auto", group="ship",
                )
                if hitbox_source is not None:
                    kw["hitbox_source"] = hitbox_source
                s = self.track(Sprite(Sheet(path, cols=4, fps=8), **kw))
                s.collidable = True
                ships.append(s)
            return ships

        def _run(ships):
            hits.clear()
            get_collision_system().step()
            n_hits = len(hits)
            base = [int(s._collision_epoch) for s in ships]
            for _ in range(12):
                clock.advance(0.125)
                get_collision_system().step()
            bumps = sum(int(s._collision_epoch) - b for s, b in zip(ships, base))
            for s in ships:
                s.destroy()
            return bumps, n_hits

        frozen_bumps, frozen_hits = _run(_fleet())
        each_bumps, each_hits = _run(_fleet(hitbox_source="each"))
        self.assertLess(frozen_bumps, each_bumps)
        self.assertGreater(frozen_hits, 0)
        self.assertEqual(frozen_hits, each_hits)

    def test_cause4_baked_extents_hold_when_clip_aspect_differs(self):
        """Frozen locals map through the reference cell, not the playhead's design box."""
        png = self.tmp("aspect.png")
        info = skia.ImageInfo.Make(16, 16, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        c = surf.getCanvas()
        c.drawRect(skia.Rect.MakeXYWH(0, 0, 8, 8), skia.Paint(Color=skia.ColorWHITE))
        c.drawRect(skia.Rect.MakeXYWH(8, 0, 8, 16), skia.Paint(Color=skia.ColorWHITE))
        surf.makeImageSnapshot().save(png, skia.kPNG)
        atlas = self.tmp("aspect.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {"image": os.path.basename(png)},
                "frames": {
                    "small": {"frame": {"x": 0, "y": 0, "w": 8, "h": 8}},
                    "tall": {"frame": {"x": 8, "y": 0, "w": 8, "h": 16}},
                },
            }, f)
        sheet = Sheet(png, atlas=atlas)
        sheet.clip("tall", ["tall"], fps=1)
        s = self.track(Sprite(
            sheet, frame="small", center=(0, 0), height=16, hitbox_shape="auto",
        ))
        s.collidable = True
        self.assertGreater(s._hitbox_ref_src_w, 0.0)
        fingerprint = s._collision_specs()
        s.play("tall")
        self.assertEqual(s._collision_specs(), fingerprint)

    def test_frozen_rect_holds_when_play_retargets_aspect(self):
        """``height=`` + wider clip must grow the sprite, not the frozen hitbox."""
        idle = self.tmp("idle.png")
        run = self.tmp("run.png")
        _write_rect_png(idle, 8, 16)
        _write_rect_png(run, 16, 16)
        sheet = Sheet([idle, run])
        sheet.clip("idle", [idle], fps=1)
        sheet.clip("run", [run], fps=1)
        s = self.track(Sprite(
            sheet, frame=0, center=(0, 0), height=32,
            hitbox_shape="rect", hitbox_source="all", hitbox_anchor="bottom",
        ))
        s.collidable = True
        w_idle = float(s.width)
        specs = s._collision_specs()
        s.play("run")
        self.assertGreater(float(s.width), w_idle)
        self.assertAlmostEqual(float(s.height), 32.0)
        self.assertEqual(s._collision_specs(), specs)

    def test_all_union_feet_follow_blit_not_source_pixels(self):
        """The union matches the blit: every cell at one scale, on the anchor.

        Idle is 20×40, run is 60×80, ``height=40`` → 1 du/px, so run draws
        60×80. With ``Sheet(anchor="bottom")`` both stand on ``center``: the
        union shares the feet line (0) and takes run's height and width.
        """
        idle = self.tmp("idle.png")
        run = self.tmp("run.png")
        _write_rect_png(idle, 20, 40)
        _write_rect_png(run, 60, 80)
        sheet = Sheet([idle, run], anchor="bottom")
        sheet.clip("idle", [idle], fps=1)
        sheet.clip("run", [run], fps=1)
        s = self.track(Sprite(
            sheet, frame=0, center=(0, 0), height=40,
            hitbox_shape="rect", hitbox_source="all", hitbox_anchor="bottom",
        ))
        s.collidable = True
        prim = snapshot_shape(s)[0]
        self.assertAlmostEqual(prim.aabb[1], 0.0, places=1)
        self.assertAlmostEqual(prim.aabb[3] - prim.aabb[1], 80.0, places=1)
        self.assertAlmostEqual(prim.aabb[2] - prim.aabb[0], 60.0, places=1)

    def test_clip_union_keeps_each_cell_at_its_own_size(self):
        """A narrower cell in a clip is not stretched to the clip's first frame."""
        anchor = self.tmp("anchor.png")
        narrow = self.tmp("narrow.png")
        _write_inset_png(anchor, 40, 40, (10, 10, 20, 20))
        _write_rect_png(narrow, 20, 40)
        sheet = Sheet([anchor, narrow])
        sheet.clip("run", [anchor, narrow], fps=1)
        s = self.track(Sprite(
            sheet, frame=0, center=(0, 0), height=40,
            hitbox_shape="rect", hitbox_source="run",
        ))
        s.collidable = True
        prim = snapshot_shape(s)[0]
        # Inset 20×20 art ∪ narrow 20×40, both centred at 1 du/px.
        self.assertAlmostEqual(prim.aabb[2] - prim.aabb[0], 20.0, places=1)
        self.assertAlmostEqual(prim.aabb[3] - prim.aabb[1], 40.0, places=1)

    def test_each_emits_through_the_baked_cell(self):
        """``each`` refits the cell and maps it at its own size (one scale)."""
        anchor = self.tmp("anchor.png")
        narrow = self.tmp("narrow.png")
        _write_rect_png(anchor, 40, 40)
        _write_rect_png(narrow, 20, 40)
        sheet = Sheet([anchor, narrow])
        sheet.clip("run", [anchor, narrow], fps=1)
        s = self.track(Sprite(
            sheet, frame=0, center=(0, 0), height=40,
            hitbox_shape="rect", hitbox_source="each",
        ))
        s.play("run")
        s.collidable = True
        clock.advance(1.0)
        prim = snapshot_shape(s)[0]
        self.assertEqual(s.frame, 1)
        # ``width`` reports the clip's first cell; the narrow cell draws 20 wide.
        self.assertAlmostEqual(float(s.width), 40.0, places=3)
        self.assertAlmostEqual(prim.aabb[2] - prim.aabb[0], 20.0, places=1)
        self.assertAlmostEqual(prim.aabb[1], -20.0, places=1)


class TestHitboxAnchorScale(SpriteTestCase):
    def test_scale_scalar_broadcasts_and_getter_is_tuple(self):
        s = self.track(Sprite(center=(0, 0), size=32, hitbox_shape="rect"))
        self.assertEqual(s.hitbox.scale, (1.0, 1.0))
        s.hitbox.scale = 0.5
        self.assertEqual(s.hitbox.scale, (0.5, 0.5))
        s.hitbox.scale = (0.55, 1.0)
        self.assertEqual(s.hitbox.scale, (0.55, 1.0))

    def test_scale_rejects_junk(self):
        s = self.track(Sprite(center=(0, 0), size=32))
        s.hitbox.scale = 0
        self.assertEqual(s.hitbox.scale[0], 0.0)
        with self.assertRaises(ValueError):
            s.hitbox.scale = -1
        with self.assertRaises(TypeError):
            s.hitbox.scale = True
        with self.assertRaises(TypeError):
            s.hitbox.scale = None
        with self.assertRaises(TypeError):
            s.hitbox.scale = (1.0,)
        with self.assertRaises(TypeError):
            s.hitbox.scale = (1.0, 1.0, 1.0)

    def test_anchor_bottom_holds_min_y(self):
        path = self.tmp("padded.png")
        _write_padded_png(path, canvas_w=64, canvas_h=64, blob=(20, 8, 24, 40))
        s = self.track(Sprite(
            path, center=(0, 0), width=64, height=64,
            hitbox_shape="rect", hitbox_anchor="bottom",
        ))
        miny0 = snapshot_shape(s)[0].aabb[1]
        s.hitbox.scale = 0.5
        miny_half = snapshot_shape(s)[0].aabb[1]
        self.assertAlmostEqual(miny_half, miny0, places=3)
        s.hitbox.scale = (0.55, 0.7)
        miny_pair = snapshot_shape(s)[0].aabb[1]
        self.assertAlmostEqual(miny_pair, miny0, places=3)

    def test_anchors_survive_rotation_and_flip_x(self):
        path = self.tmp("padded.png")
        _write_padded_png(path, canvas_w=64, canvas_h=64, blob=(20, 8, 24, 40))
        s = self.track(Sprite(
            path, center=(0, 0), width=64, height=64,
            hitbox_shape="rect", hitbox_anchor="bottom", hitbox_scale=(0.5, 1.0),
        ))
        miny = snapshot_shape(s)[0].aabb[1]
        s.flip_x = True
        self.assertAlmostEqual(snapshot_shape(s)[0].aabb[1], miny, places=3)
        s.flip_x = False
        local0 = s._local_prims_aabb()
        s.angle = 90
        self.assertEqual(s._local_prims_aabb(), local0)

    def test_circle_nonuniform_scale_emits_ellipse(self):
        path = self.tmp("disk.png")
        _write_disk_png(path, side=64, radius=28)
        s = self.track(Sprite(
            path, center=(0, 0), width=64, height=64,
            hitbox_shape="circle", hitbox_scale=(0.5, 1.0),
        ))
        prim = snapshot_shape(s)[0]
        self.assertEqual(prim.kind, PrimKind.ELLIPSE)
        self.assertAlmostEqual(prim.params[2] / prim.params[3], 0.5, places=2)

    def test_ellipse_hitbox_scale_is_per_axis(self):
        """Non-square ellipse: sx must not change world ry (and vice versa).

        SVD of local (nrx, nry) sorts singular values and can rotate onto 90°,
        after which emit multiplies the swapped radii by the wrong pose axis.
        """
        path = self.tmp("tall.png")
        _write_rect_png(path, 40, 100)
        s = self.track(Sprite(
            path, center=(0, 0), width=40, height=100, hitbox_shape="ellipse",
        ))
        prim0 = snapshot_shape(s)[0]
        self.assertEqual(prim0.kind, PrimKind.ELLIPSE)
        rx0, ry0 = float(prim0.params[2]), float(prim0.params[3])
        self.assertGreater(ry0, rx0)

        s.hitbox.scale = (0.5, 1.0)
        prim = snapshot_shape(s)[0]
        self.assertEqual(prim.kind, PrimKind.ELLIPSE)
        self.assertAlmostEqual(float(prim.params[2]), rx0 * 0.5, places=3)
        self.assertAlmostEqual(float(prim.params[3]), ry0, places=3)
        self.assertAlmostEqual(abs(math.sin(float(prim.params[4]))), 0.0, places=4)

        s.hitbox.scale = (1.0, 0.5)
        prim = snapshot_shape(s)[0]
        self.assertEqual(prim.kind, PrimKind.ELLIPSE)
        self.assertAlmostEqual(float(prim.params[2]), rx0, places=3)
        self.assertAlmostEqual(float(prim.params[3]), ry0 * 0.5, places=3)
        self.assertAlmostEqual(abs(math.sin(float(prim.params[4]))), 0.0, places=4)

    def test_rotated_ellipse_bottom_anchor_matches_drawn_edge(self):
        """A ~90° ellipse on a tall cell must pin its drawn bottom, not a fake AABB.

        ``nrx`` is a fraction of width and ``nry`` of height. Treating them as
        one Euclidean space inflates the box and lifts the oval off the feet.
        """
        path = self.tmp("tall.png")
        _write_rect_png(path, 40, 100)
        s = self.track(Sprite(
            path, center=(0, 0), width=40, height=100,
            hitbox_shape="ellipse", hitbox_anchor="bottom",
        ))
        snapshot_shape(s)
        ang = -math.pi / 2
        base = ((0.0, 0.05, 0.9, 0.12, ang),)
        s._hitbox_base_ellipses = base
        s._hitbox_base_ellipse = base[0]
        s._hitbox_base_circles = ()
        s._hitbox_base_circle = None
        s._hitbox_base_boxes = ()
        s._hitbox_base_poly = ()
        s._apply_hitbox_shaping()
        prim = snapshot_shape(s)[0]
        self.assertEqual(prim.kind, PrimKind.ELLIPSE)
        self.assertAlmostEqual(prim.aabb[1], -50.0, places=2)
        # Marker uses this local bottom × pose height. It must sit on the oval.
        self.assertAlmostEqual(s._local_prims_aabb()[1] * 100.0, prim.aabb[1], places=2)

    def test_circle_bottom_anchor_on_tall_cell_matches_drawn_edge(self):
        """Circle radius is a fraction of width; the y pin must scale it by aspect."""
        path = self.tmp("tall.png")
        _write_rect_png(path, 40, 100)
        s = self.track(Sprite(
            path, center=(0, 0), width=40, height=100,
            hitbox_shape="circle", hitbox_anchor="bottom",
        ))
        snapshot_shape(s)
        base = ((0.0, 0.0, 0.4),)
        s._hitbox_base_circles = base
        s._hitbox_base_circle = base[0]
        s._hitbox_base_ellipses = ()
        s._hitbox_base_ellipse = None
        s._hitbox_base_boxes = ()
        s._hitbox_base_poly = ()
        s._apply_hitbox_shaping()
        prim = snapshot_shape(s)[0]
        self.assertEqual(prim.kind, PrimKind.CIRCLE)
        self.assertAlmostEqual(float(prim.params[2]), 16.0, places=2)
        self.assertAlmostEqual(prim.aabb[1], -50.0, places=2)

    def test_ellipse_x_scale_about_bottom_holds_height(self):
        path = self.tmp("tall.png")
        _write_rect_png(path, 40, 100)
        s = self.track(Sprite(
            path, center=(0, 0), width=40, height=100,
            hitbox_shape="ellipse", hitbox_anchor="bottom",
        ))
        prim0 = snapshot_shape(s)[0]
        self.assertEqual(prim0.kind, PrimKind.ELLIPSE)
        miny0 = prim0.aabb[1]
        ry0 = float(prim0.params[3])
        s.hitbox.scale = (0.35, 1.0)
        prim = snapshot_shape(s)[0]
        self.assertEqual(prim.kind, PrimKind.ELLIPSE)
        self.assertAlmostEqual(float(prim.params[3]), ry0, places=3)
        self.assertAlmostEqual(prim.aabb[1], miny0, places=3)
        self.assertAlmostEqual(abs(math.sin(float(prim.params[4]))), 0.0, places=4)

    def test_rotated_ellipse_nonuniform_scale_matches_conic(self):
        path = self.tmp("wide.png")
        _write_rect_png(path, 100, 40)
        s = self.track(Sprite(path, center=(0, 0), width=100, height=40, hitbox_shape="ellipse"))
        snapshot_shape(s)
        ang = math.radians(35.0)
        s._hitbox_ellipses = ((0.0, 0.0, 0.4, 0.15, ang),)
        s._hitbox_ellipse = s._hitbox_ellipses[0]
        s._hitbox_base_ellipses = s._hitbox_ellipses
        s._hitbox_base_ellipse = s._hitbox_ellipse
        s._hitbox_circles = ()
        s._hitbox_circle = None
        s._hitbox_boxes = ()
        s._hitbox_poly = ()
        s._auto_baked = True
        prim0 = snapshot_shape(s)[0]
        self.assertEqual(prim0.kind, PrimKind.ELLIPSE)
        rx0, ry0, ang0 = (float(prim0.params[2]), float(prim0.params[3]),
                          float(prim0.params[4]))
        s.hitbox.scale = (0.5, 1.0)
        prim = snapshot_shape(s)[0]
        self.assertEqual(prim.kind, PrimKind.ELLIPSE)
        rx, ry, ang1 = (float(prim.params[2]), float(prim.params[3]),
                        float(prim.params[4]))
        g0 = _ellipse_gram(rx0, ry0, ang0)
        got = _ellipse_gram(rx, ry, ang1)
        exp = (0.25 * g0[0], 0.5 * g0[1], g0[2])
        for a, b in zip(got, exp):
            self.assertAlmostEqual(a, b, places=4)


class TestSpriteOverlays(unittest.TestCase):
    """Slice 6: overlay looks + Electric*/Shield ellipse on Sprite."""

    def setUp(self):
        from scena import init
        from scena.canvas import ScenaCanvas
        reset_sprite_caches()
        reset_process_scheduler()
        reset_collision_system()
        cleanup_global_event_system()
        if ScenaCanvas.get_current() is None:
            init(width=400, height=300, title="sprite-overlay-test")
        self._tracked = []

    def tearDown(self):
        for s in self._tracked:
            try:
                if getattr(s, "is_alive", True):
                    s.destroy()
            except Exception:
                pass
        self._tracked.clear()

    def track(self, s):
        self._tracked.append(s)
        return s

    def test_default_fill_is_sprite_body(self):
        s = self.track(Sprite(center=(0, 0), size=20))
        self.assertTrue(is_sprite_body(s._fill))
        self.assertIs(s.visual, None)

    def test_overlay_looks_assign(self):
        s = self.track(Sprite(center=(100, 100), size=32))
        for look in (
            Halo(),
            Halo(style="fill"), Halo(style="soft"), Halo(style="line"),
            Halo(style="pulse"),
            Beat(),
            ElectricField(), ElectricBolt(),
            Shield(style="bubble"), Shield(style="plasma"),
            Recolor(), Aura(), EmissiveBloom(), Rim(),
            DashRing(), GearShell(), Laser(), Ink(), InkBleed(),
            Metal(), Flame(), Swell(), Aurora(), Wave(), Extrude(angle=200),
            MultiBorder(), OrganicOutline(), Tracer(),
        ):
            s.visual = look
            self.assertIs(s.visual, look)
            self.assertTrue(getattr(look, "_allows_sprite", False))
        s.glow = Glow()
        self.assertIsInstance(s.glow, Glow)
        s.shadow = Shadow()
        self.assertIsInstance(s.shadow, Shadow)
        s.tail = Tail()
        self.assertIsInstance(s.tail, Tail)
        s.hue = HueShift(amount=0.2)
        self.assertIsInstance(s.hue, HueShift)
        s.visual = None
        s.glow = None
        s.shadow = None
        s.tail = None
        s.hue = None
        self.assertTrue(is_sprite_body(s._fill))

    def test_hue_shift_plain_blit_and_no_glow_filter(self):
        s = self.track(Sprite(center=(0, 0), size=24))
        s.hue = HueShift(amount=0.33)
        self.assertIsNone(s.fill_filter)
        self.assertIsNotNone(s._blit_color_filter)
        self.assertTrue(s._plain_blit)

    def test_sprite_only_looks_rejected_on_shape(self):
        c = Circle(center=(0, 0), radius=10)
        self.addCleanup(c.destroy)
        with self.assertRaises(TypeError) as ctx:
            c.visual = HueShift(amount=0.1)
        msg = str(ctx.exception).lower()
        self.assertIn("stamp", msg)
        self.assertIn("shift=", msg)
        # Aura and EmissiveBloom wear a Shape too since 2026-10-27
        # (test_shape_pixel_looks); Recolor changes an image's pixels.
        with self.assertRaises(TypeError) as ctx:
            c.visual = Recolor()
        msg = str(ctx.exception).lower()
        self.assertIn("sprite-only", msg)
        self.assertIn("shift=", msg)
        c.visual = Rim()
        self.assertIsInstance(c.visual, Rim)

    def test_shield_ellipse_scale(self):
        s = self.track(Sprite(center=(0, 0), width=40, height=20))
        s.visual = ElectricField()
        self.assertAlmostEqual(_sprite_ellipse_scale(s), 1.0)
        s.visual = Shield(style="bubble")
        self.assertAlmostEqual(_sprite_ellipse_scale(s), _SPRITE_SHIELD_SCALE)
        self.assertAlmostEqual(s.shield_scale, 1.4)
        _cx, _cy, ew, eh, _ang = s._shield_envelope_frame()
        # Placeholder is opaque → envelope ≈ design box; draw size is ×shield_scale.
        self.assertAlmostEqual(ew, 40.0 * 1.4, places=2)
        self.assertAlmostEqual(eh, 20.0 * 1.4, places=2)
        s.shield_scale = 2.0
        self.assertAlmostEqual(_sprite_ellipse_scale(s), 2.0)
        _cx, _cy, ew2, eh2, _ang = s._shield_envelope_frame()
        self.assertAlmostEqual(ew2, 40.0 * 2.0, places=2)
        self.assertAlmostEqual(eh2, 20.0 * 2.0, places=2)

    def test_frame_fx_shared_across_sprites(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        a = self.track(Sprite(path, size=32, center=(0, 0)))
        b = self.track(Sprite(path, size=40, center=(10, 10)))
        a.visual = Aura()
        n = len(_FRAME_FX_CACHE)
        self.assertGreater(n, 0)  # assign-time bake; no draw needed
        b.visual = Aura(amount=1.1)
        self.assertEqual(len(_FRAME_FX_CACHE), n)

    def test_frame_fx_no_bake_on_plain_or_glow(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(path, size=32, center=(0, 0)))
        self.assertEqual(len(_FRAME_FX_CACHE), 0)
        s.glow = Glow()
        self.assertEqual(len(_FRAME_FX_CACHE), 0)

    def test_frame_fx_halo_bakes_at_assign(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(path, size=32, center=(0, 0)))
        s.visual = Halo()
        self.assertEqual(len(_FRAME_FX_CACHE), 1)
        fx = next(iter(_FRAME_FX_CACHE.values()))
        self.assertIsNotNone(fx.path)
        self.assertFalse(fx.path.isEmpty())
        # Sprite Halo uses SDF bands — assign warms SDF too.
        self.assertIsNotNone(fx.sdf)

    def test_frame_fx_aura_bakes_sdf_at_assign(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(path, size=32, center=(0, 0)))
        s.visual = Aura()
        fx = next(iter(_FRAME_FX_CACHE.values()))
        self.assertIsNotNone(fx.sdf)

    def test_frame_fx_ctor_visual_bakes(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        self.track(Sprite(path, size=32, center=(0, 0)))
        self.assertEqual(len(_FRAME_FX_CACHE), 0)
        reset_sprite_caches()
        self.track(Sprite(path, size=32, center=(0, 0), visual=Halo()))
        self.assertEqual(len(_FRAME_FX_CACHE), 1)

    def test_frame_fx_strip_warms_all_cells(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(Sheet(path, cols=4), size=32, center=(0, 0)))
        self.assertEqual(s.sheet.nframes, 4)
        s.visual = Halo()
        self.assertEqual(len(_FRAME_FX_CACHE), 1)
        s.prepare_fx(Halo)
        self.assertEqual(len(_FRAME_FX_CACHE), 4)

    def test_frame_fx_survives_destroy_recreate(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        a = self.track(Sprite(path, size=32, center=(0, 0), visual=Halo()))
        n = len(_FRAME_FX_CACHE)
        self.assertEqual(n, 1)
        a.destroy()
        b = self.track(Sprite(path, size=32, center=(10, 10), visual=Halo()))
        self.assertEqual(len(_FRAME_FX_CACHE), n)
        self.assertIsNotNone(b.visual)

    def test_prepare_fx_noop_on_shape(self):
        c = self.track(Circle(center=(0, 0), radius=10))
        out = c.prepare_fx(Halo)
        self.assertIs(out, c)

    def test_prepare_fx_no_args_without_visual(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(path, size=32, center=(0, 0)))
        s.prepare_fx()
        self.assertEqual(len(_FRAME_FX_CACHE), 0)
        s.glow = Glow()
        s.prepare_fx()
        self.assertEqual(len(_FRAME_FX_CACHE), 0)

    def test_prepare_fx_aura_without_assigning_visual(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(path, size=32, center=(0, 0)))
        s.prepare_fx(Aura)
        self.assertIsNone(s.visual)
        self.assertEqual(len(_FRAME_FX_CACHE), 1)
        fx = next(iter(_FRAME_FX_CACHE.values()))
        self.assertIsNotNone(fx.sdf)

    def test_prepare_fx_glow_is_noop(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(path, size=32, center=(0, 0)))
        s.prepare_fx(Glow)
        self.assertEqual(len(_FRAME_FX_CACHE), 0)

    def test_frame_fx_path_only_then_sdf_upgrade(self):
        """DashRing warms path only; Aura upgrade fills SDF in place."""
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(path, size=32, center=(0, 0)))
        s.visual = DashRing()
        self.assertEqual(len(_FRAME_FX_CACHE), 1)
        fx = next(iter(_FRAME_FX_CACHE.values()))
        self.assertIsNotNone(fx.path)
        self.assertIsNone(fx.sdf)
        s.visual = Aura()
        self.assertEqual(len(_FRAME_FX_CACHE), 1)
        self.assertIsNotNone(fx.sdf)

    def test_frame_fx_available_at_survival(self):
        """Low quality still exposes silhouette path (not ellipse-only)."""
        path = media("k-rolling-ball", "ball_red_large.png")
        from scena.fx_quality import activate_quality, active_fx_quality
        prev = active_fx_quality()
        try:
            activate_quality("low")
            reset_sprite_caches()
            s = self.track(Sprite(path, size=32, center=(0, 0)))
            fx = s._frame_fx()
            self.assertIsNotNone(fx)
            self.assertFalse(fx.empty)
            self.assertIsNotNone(fx.path)
            self.assertFalse(fx.path.isEmpty())
        finally:
            activate_quality(prev)

    def test_frame_fx_path_v2_is_simpler(self):
        """v2 contour is a subset; v1 path still exists for original looks."""
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(path, size=32, center=(0, 0)))
        fx = s._frame_fx()
        self.assertIsNotNone(fx.path)
        self.assertIsNotNone(fx.path_v2)
        self.assertFalse(fx.path_v2.isEmpty())
        self.assertGreater(fx.n_path, 0)
        self.assertGreaterEqual(fx.n_path_v2, 4)
        self.assertLessEqual(fx.n_path_v2, fx.n_path)

    def test_silhouette_v2_draw_and_cache(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(path, size=32, center=(0, 0)))
        from scena.canvas import ScenaCanvas
        eng = ScenaCanvas.get_current()
        paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=2.0)
        self.assertTrue(s._draw_sprite_silhouette_v2(eng.skia_canvas, paint))
        fx = s._frame_fx()
        self.assertIsNotNone(fx.local_v2)
        self.assertGreater(len(fx.local_v2), 0)
        s._draw_sprite_silhouette_v2(eng.skia_canvas, paint)
        n = len(fx.local_v2)
        s._draw_sprite_silhouette_v2(eng.skia_canvas, paint)
        self.assertEqual(len(fx.local_v2), n)

    def test_halo_laser_sprite_v2_shape_keeps_v1(self):
        """Sprite Halo/Laser/Rim use the SDF path; Shape Halo/Rim still batch Blur."""
        from scena.canvas import ScenaCanvas
        from scena import Blur
        from scena.fx_quality import activate_quality, active_fx_quality
        prev = active_fx_quality()
        try:
            activate_quality("high")
            eng = ScenaCanvas.get_current()
            s = self.track(Sprite(center=(40, 40), size=32))
            s.visual = Halo("cyan")
            self.assertIsNone(s.line_filter)
            self.assertIsNone(s.fill_filter)
            self.assertTrue(callable(getattr(s.visual, "_render_sprite_body", None)))
            s.draw(eng.skia_canvas)
            s.visual = Halo("cyan", style="fill")
            self.assertIsNone(s.line_filter)
            s.draw(eng.skia_canvas)
            s.visual = Laser("tomato")
            s.draw(eng.skia_canvas)
            s.visual = Rim("white")
            self.assertIsNone(s.line_filter)
            self.assertIsNone(s.fill_filter)
            self.assertTrue(callable(getattr(s.visual, "_render_sprite_body", None)))
            s.draw(eng.skia_canvas)
            c = Circle(center=(80, 80), radius=16)
            self.addCleanup(c.destroy)
            c.visual = Halo("cyan")
            self.assertIsInstance(c.line_filter, Blur)
            c.draw(eng.skia_canvas)
            c.visual = Laser()
            c.draw(eng.skia_canvas)
            c.visual = Rim("white")
            self.assertIsInstance(c.line_filter, Blur)
            c.draw(eng.skia_canvas)
        finally:
            activate_quality(prev)

    def test_halo_line_sprite_keeps_hostglow_not_sdf(self):
        """Halo(style='line') must not inherit Halo.render_sprite (_seed crash)."""
        from scena.canvas import ScenaCanvas
        from scena.fx_quality import activate_quality, active_fx_quality
        prev = active_fx_quality()
        try:
            activate_quality("high")
            eng = ScenaCanvas.get_current()
            s = self.track(Sprite(center=(40, 40), size=32))
            s.visual = Halo("lime", style="line")
            self.assertFalse(callable(getattr(s.visual, "_render_sprite_body", None)))
            self.assertFalse(bool(s.fill))
            self.assertIsInstance(s.line_filter, HostGlow)
            s.draw(eng.skia_canvas)
            activate_quality("low")
            s.visual._apply(s)
            self.assertIsNone(s.line_filter)
            s.draw(eng.skia_canvas)
        finally:
            activate_quality(prev)

    def test_visual_kwarg_on_construct(self):
        s = self.track(Sprite(center=(0, 0), size=24))
        s.glow = Glow(color="cyan")
        self.assertIsInstance(s.glow, Glow)
        self.assertIsNone(s.visual)
        self.assertIsNotNone(s.fill_filter)

    def test_glow_uses_fill_filter_not_line(self):
        s = self.track(Sprite(center=(0, 0), size=24))
        s.glow = Glow()
        self.assertIsNotNone(s.fill_filter)
        self.assertIsNone(s.line_filter)

    def test_forcefield_kind_is_ellipse(self):
        s = self.track(Sprite(center=(50, 60), width=40, height=20))
        self.assertEqual(_forcefield_kind(s), "ellipse")
        cx, cy, w, h, ang = _ellipse_params(s)
        self.assertAlmostEqual(cx, 50.0, places=4)
        self.assertAlmostEqual(cy, 60.0, places=4)
        self.assertAlmostEqual(w, 40.0, places=4)
        self.assertAlmostEqual(h, 20.0, places=4)

    def test_ellipse_params_follow_rotation(self):
        s = self.track(Sprite(center=(0, 0), width=40, height=20))
        s.angle = 30.0
        *_rest, ang = _ellipse_params(s)
        self.assertAlmostEqual(ang, 30.0, places=4)

    def test_geometry_stroke_is_ellipse_not_rect(self):
        """Stroke override must hit the sprite-rect oval (Electric*/Halo path)."""
        s = self.track(Sprite(center=(0, 0), width=80, height=40))
        from scena.canvas import ScenaCanvas
        eng = ScenaCanvas.get_current()
        paint = skia.Paint(
            AntiAlias=True,
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=2.0,
            Color=skia.ColorWHITE,
        )
        # Corner of AABB is outside the ellipse → must not be covered by stroke-only pass.
        s._geometry_draw(eng.skia_canvas, fill_paint=None, stroke_paint=paint)
        # Smoke: oriented frame matches ellipse params used by forcefields.
        self.assertEqual(_ellipse_params(s)[2:], (80.0, 40.0, 0.0))

    def test_shield_keeps_image_body_after_clear(self):
        s = self.track(Sprite(center=(0, 0), size=30))
        s.visual = Shield(style="nebula")
        self.assertFalse(is_sprite_body(s._fill))  # ProceduralFill costume
        s.visual = None
        self.assertTrue(is_sprite_body(s._fill))

    def test_water_flame_texture_rejected(self):
        s = self.track(Sprite(center=(0, 0), size=20))
        for look in (Water(), Paint("coral"), Neon()):
            with self.assertRaises(TypeError) as ctx:
                s.visual = look
            self.assertIn("Sprite.visual", str(ctx.exception))
        # Flame / Metal now legal (silhouette body)
        s.visual = Flame()
        self.assertIsInstance(s.visual, Flame)

    def test_quality_gate_does_not_crash_sprite_electric(self):
        from scena import canvas
        s = self.track(Sprite(center=(0, 0), size=28))
        from scena.canvas import ScenaCanvas
        eng = ScenaCanvas.get_current()
        for q in ("low", "medium", "high"):
            canvas.fx_quality = q
            s.visual = ElectricField()  # re-apply under quality
            s.draw(eng.skia_canvas)
        canvas.fx_quality = "high"
    def test_tail_and_beat_draw(self):
        from scena.canvas import ScenaCanvas
        eng = ScenaCanvas.get_current()
        s = self.track(Sprite(center=(10, 10), size=24))
        s.tail = Tail(angle=90, size=1.2)
        s.draw(eng.skia_canvas)
        s.visual = Beat(amount=0.1)
        s.draw(eng.skia_canvas)


class TestSaveVisualSprite(unittest.TestCase):
    """save_visual / restore_visual on Sprite."""

    def setUp(self):
        from scena import init
        from scena.canvas import ScenaCanvas
        reset_sprite_caches()
        reset_process_scheduler()
        reset_collision_system()
        cleanup_global_event_system()
        if ScenaCanvas.get_current() is None:
            init(width=400, height=300, title="sprite-save-visual-test")
        self._tracked = []

    def tearDown(self):
        for s in self._tracked:
            try:
                if getattr(s, "is_alive", True):
                    s.destroy()
            except Exception:
                pass

    def track(self, s):
        self._tracked.append(s)
        return s

    def test_save_restore_glow(self):
        s = self.track(Sprite(center=(0, 0), size=32))
        glow = Glow("skyblue")
        s.glow = glow
        s.save_visual()
        s.visual = Halo("gold")
        s.glow = None
        s.restore_visual()
        self.assertIs(s.glow, glow)
        self.assertIsNone(s.visual)
        self.assertTrue(is_sprite_body(s._fill))

    def test_group_save_restore(self):
        a = self.track(Sprite(center=(0, 0), size=24, group="pair"))
        b = self.track(Sprite(center=(40, 0), size=24, group="pair"))
        ga = Glow()
        gb = Halo()
        a.glow = ga
        b.visual = gb
        group["pair"].save_visual()
        group["pair"].visual = Shield(style="bubble")
        group["pair"].restore_visual()
        self.assertIs(a.glow, ga)
        self.assertIsNone(a.visual)
        self.assertIs(b.visual, gb)

    def test_redundant_visual_assign_skips_frame_fx_warm(self):
        path = media("k-rolling-ball", "ball_red_large.png")
        reset_sprite_caches()
        s = self.track(Sprite(Sheet(path, cols=4), size=32, center=(0, 0)))
        calls = []

        def counting_warm(self, *, sdf=False):
            calls.append(sdf)

        orig = Sprite._warm_frame_fx
        try:
            Sprite._warm_frame_fx = counting_warm
            s.visual = Halo("gold")
            self.assertEqual(len(calls), 1)
            s.visual = Halo("gold")
            self.assertEqual(len(calls), 1)
        finally:
            Sprite._warm_frame_fx = orig


class TestGreedyHitbox(unittest.TestCase):
    def test_empty_mask(self):
        from scena.atlas import greedy_rects
        import numpy as np
        self.assertEqual(greedy_rects(np.zeros((8, 8), dtype=bool)), [])

    def test_single_rect(self):
        from scena.atlas import greedy_rects
        import numpy as np
        m = np.zeros((8, 8), dtype=bool)
        m[2:5, 1:6] = True
        self.assertEqual(greedy_rects(m), [(1, 2, 5, 3)])

    def test_caps_at_five_drops_remainder_no_leftover_aabb(self):
        from scena.atlas import greedy_rects
        import numpy as np
        m = np.zeros((16, 16), dtype=bool)
        for i in range(6):
            m[i * 2, i * 2] = True
        rects = greedy_rects(m, max_rects=5)
        self.assertEqual(len(rects), 5)
        # Every rect is a tight 1×1 — not one AABB covering the diagonal.
        for x, y, w, h in rects:
            self.assertEqual((w, h), (1, 1))

    def test_fit_circle_accepts_disk_rejects_l(self):
        from scena.atlas import fit_circle
        import numpy as np
        disk = np.zeros((32, 32), dtype=bool)
        yy, xx = np.ogrid[:32, :32]
        disk[(xx - 15.5) ** 2 + (yy - 15.5) ** 2 <= 14 ** 2] = True
        hit = fit_circle(disk)
        self.assertIsNotNone(hit)
        self.assertGreater(hit[2], 10.0)
        L = np.zeros((32, 32), dtype=bool)
        L[:, :8] = True
        L[24:, :] = True
        self.assertIsNone(fit_circle(L))


class TestSpriteClone(SpriteTestCase):
    def test_clone_copies_a_main_hitbox_switched_off(self):
        # A clone collides like its source (review 2026-10-09 S7-8).
        path = self.tmp("ghost.png")
        _write_rect_png(path, 8, 8)
        src = self.track(Sprite(path, height=18, center=(0, 0)))
        src.hitbox.active = False
        copy = self.track(src.clone(center=(40, 0)))
        self.assertFalse(copy.hitbox.active)
        on = self.track(Sprite(path, height=18, center=(0, 0)))
        self.assertTrue(self.track(on.clone()).hitbox.active)

    def test_clone_shares_sheet_identity(self):
        path = self.tmp("shot.png")
        _write_rect_png(path, 8, 8)
        src = self.track(Sprite(path, height=18, center=(0, 0), group="sting"))
        copy = self.track(src.clone(center=(40, 50)))
        self.assertIs(copy.sheet, src.sheet)
        self.assertIsNot(copy, src)
        self.assertAlmostEqual(float(copy.center.x), 40)
        self.assertAlmostEqual(float(copy.center.y), 50)

    def test_clone_is_independently_destroyable(self):
        path = self.tmp("shot.png")
        _write_rect_png(path, 8, 8)
        src = self.track(Sprite(path, height=18, center=(0, 0)))
        copy = self.track(src.clone(center=(10, 0)))
        copy.destroy()
        self.assertFalse(copy.is_alive)
        self.assertTrue(src.is_alive)

    def test_subclass_clone_runs_setup(self):
        path = self.tmp("shot.png")
        _write_rect_png(path, 8, 8)

        class Sting(Sprite):
            setups = 0

            def setup(self):
                Sting.setups += 1
                self.glow = CheapGlow(color="tomato", radius=8)
                self.hp = 3

        src = self.track(Sting(path, height=18, center=(0, 0), group="sting", layer=None))
        self.assertEqual(Sting.setups, 1)
        self.assertIsNone(src.layer)
        copy = self.track(src.clone(center=(20, 30)))
        self.assertIsInstance(copy, Sting)
        self.assertEqual(Sting.setups, 2)
        self.assertEqual(float(copy.hp), 3)
        self.assertEqual(copy.layer, canvas.layers.default)
        self.assertIn("sting", copy.group)
        self.assertIn(copy, group["sting"])

    def test_clone_look_like_shares_interned_visual(self):
        path = self.tmp("shot.png")
        _write_rect_png(path, 8, 8)
        glow = CheapGlow(color="tomato", radius=8)
        src = self.track(Sprite(path, height=18, center=(0, 0)))
        src.glow = glow
        copy = self.track(src.clone(center=(4, 0)))
        self.assertIs(copy.glow, src.glow)
        other = CheapGlow(color="deepskyblue", radius=10)
        src.glow = other
        self.assertIsNot(copy.glow, src.glow)
        self.assertIs(copy.glow, glow)

    def test_clone_groups_copy_and_replace(self):
        path = self.tmp("shot.png")
        _write_rect_png(path, 8, 8)
        src = self.track(Sprite(path, height=18, center=(0, 0), group="sting"))
        src.tag("shielded")
        copied = self.track(src.clone(center=(1, 0)))
        self.assertIn("sting", copied.group)
        self.assertIn("shielded", copied.group)
        replaced = self.track(src.clone(center=(2, 0), group="other"))
        self.assertEqual(replaced.group, {"other"})
        self.assertNotIn("sting", replaced.group)

    def test_clone_layer_sentinel(self):
        path = self.tmp("shot.png")
        _write_rect_png(path, 8, 8)
        src = self.track(Sprite(path, height=18, center=(0, 0), layer=None))
        on_default = self.track(src.clone(center=(0, 0)))
        self.assertEqual(on_default.layer, canvas.layers.default)
        undrawn = self.track(src.clone(center=(0, 0), layer=None))
        self.assertIsNone(undrawn.layer)
        on_top = self.track(src.clone(center=(0, 0), layer="top"))
        self.assertEqual(on_top.layer, "top")

    def test_clone_copies_hitbox_from(self):
        path = self.tmp("strip.png")
        _write_blob_strip(path, cell=8)
        src = self.track(Sprite(
            Sheet(path, cols=4), center=(0, 0), size=16, hitbox_shape="auto", hitbox_source="all",
        ))
        copy = self.track(src.clone(center=(8, 0)))
        self.assertEqual(copy.hitbox.source, "all")
        self.assertEqual(copy.hitbox.shape, src.hitbox.shape)

    def test_clone_copies_hitbox_anchor_and_scale_pair(self):
        path = self.tmp("strip.png")
        _write_blob_strip(path, cell=8)
        src = self.track(Sprite(
            Sheet(path, cols=4), center=(0, 0), size=16,
            hitbox_shape="rect", hitbox_source="all",
            hitbox_anchor="bottom", hitbox_scale=(0.55, 1.0),
        ))
        copy = self.track(src.clone(center=(8, 0)))
        self.assertEqual(copy.hitbox.source, "all")
        self.assertEqual(copy.hitbox.anchor, "bottom")
        self.assertEqual(copy.hitbox.scale, (0.55, 1.0))

    def test_clone_playhead_starts_clean(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        src = self.track(Sprite(Sheet(path, cols=4, fps=10), center=(0, 0), size=16))
        clock.advance(0.25)
        self.assertNotEqual(src.frame, 0)
        self.assertIsNotNone(src._play_name)
        copy = self.track(src.clone(center=(8, 0)))
        self.assertIsNone(copy._play_name)
        self.assertEqual(copy.frame, src.frame)

    def test_beginner_stamp_no_sheet(self):
        path = self.tmp("fire06.png")
        _write_rect_png(path, 8, 8)

        class Sting(Sprite):
            def setup(self):
                self.glow = CheapGlow(color="tomato", radius=8)

        stamp = self.track(Sting(path, height=18, group="sting", layer=None))
        shot = self.track(stamp.clone(center=(12, 24)))
        self.assertIsInstance(shot, Sting)
        self.assertEqual(shot.layer, canvas.layers.default)
        self.assertIn("sting", shot.group)
        self.assertIs(shot.sheet, stamp.sheet)


class TestSpriteArtAngle(SpriteTestCase):
    def test_default_is_zero_and_matches_today(self):
        s = self.track(Sprite(center=(0, 0), size=32))
        self.assertAlmostEqual(s.art_angle, 0.0)
        self.assertAlmostEqual(s.angle, 0.0)
        self.assertAlmostEqual(s._draw_angle(), 0.0)

    def test_seed_heading_leaves_pixels_as_drawn(self):
        s = self.track(Sprite(
            center=(0, 0), width=20, height=20, hitbox_shape="rect",
            offset=(10, 0), art_angle=90,
        ))
        self.assertAlmostEqual(s.art_angle, 90.0)
        self.assertAlmostEqual(s.angle, 90.0)
        self.assertAlmostEqual(s._draw_angle(), 0.0)
        cx, cy, _w, _h, ang = s._oriented_frame()
        self.assertAlmostEqual(ang, 0.0)
        self.assertAlmostEqual(cx, 10.0)
        self.assertAlmostEqual(cy, 0.0)
        self.assertTrue(s.contains_point(10, 0))
        self.assertFalse(s.contains_point(0, 15))
        from scena.shapes import Point
        self.assertTrue(s.contains_point(Point(10, 0)))
        self.assertTrue(s.contains_point((10, 0)))
        self.assertFalse(s.contains_point((0, 15)))
        prim = snapshot_shape(s)[0]
        mid_x = 0.5 * (prim.aabb[0] + prim.aabb[2])
        mid_y = 0.5 * (prim.aabb[1] + prim.aabb[3])
        self.assertAlmostEqual(mid_x, 10.0, places=3)
        self.assertAlmostEqual(mid_y, 0.0, places=3)

    def test_heading_zero_points_nose_along_plus_x(self):
        s = self.track(Sprite(
            center=(0, 0), width=20, height=20, hitbox_shape="rect",
            offset=(10, 0), art_angle=90,
        ))
        s.angle = 0.0
        self.assertAlmostEqual(s._draw_angle(), -90.0)
        cx, cy, *_ = s._oriented_frame()
        # As-drawn offset (+x) then CTM −90° → (0, −10) in y-up CCW.
        self.assertAlmostEqual(cx, 0.0, places=4)
        self.assertAlmostEqual(cy, -10.0, places=4)

    def test_atan2_heading_aligns_nose(self):
        s = self.track(Sprite(
            center=(0, 0), width=20, height=20, hitbox_shape="rect",
            offset=(10, 0), art_angle=90,
        ))
        s.angle = math.degrees(math.atan2(0.0, 1.0))  # +x
        self.assertAlmostEqual(s._draw_angle(), -90.0)
        cx, cy, *_ = s._oriented_frame()
        self.assertAlmostEqual(cx, 0.0, places=4)
        self.assertAlmostEqual(cy, -10.0, places=4)

    def test_clip_shares_one_angle(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=16, cols=4, rows=1)
        s = self.track(Sprite(
            Sheet(path, cols=4, fps=8), art_angle=90, height=16, center=(0, 0),
        ))
        self.assertAlmostEqual(s.art_angle, 90.0)
        self.assertAlmostEqual(s.angle, 90.0)
        self.assertAlmostEqual(s._draw_angle(), 0.0)
        clock.advance(0.25)
        self.assertGreaterEqual(int(s.frame), 1)
        self.assertAlmostEqual(s.art_angle, 90.0)
        self.assertAlmostEqual(s._draw_angle(), 0.0)

    def test_flip_x_reflects_heading_not_art_angle(self):
        s = self.track(Sprite(
            center=(0, 0), size=32, art_angle=90, flip_x=True,
        ))
        self.assertTrue(s.flip_x)
        self.assertAlmostEqual(s.art_angle, 90.0)
        self.assertAlmostEqual(s.angle, 90.0)
        self.assertAlmostEqual(s.rest_heading, 90.0)
        self.assertAlmostEqual(s._draw_angle(), 0.0)
        plain = self.track(Sprite(center=(0, 0), size=32, flip_x=True))
        self.assertAlmostEqual(plain.angle, 180.0)
        self.assertAlmostEqual(plain._draw_angle(), 0.0)
        plain.angle = 90.0
        self.assertAlmostEqual(plain._draw_angle(), -90.0)

    def test_ninja_a_flip_equals_ninja_b(self):
        a = self.track(Sprite(center=(0, 0), size=32, art_angle=0))
        b = self.track(Sprite(center=(0, 0), size=32, art_angle=180))
        a.flip_x = True
        self.assertAlmostEqual(a.angle, 180.0)
        self.assertAlmostEqual(b.angle, 180.0)
        self.assertAlmostEqual(a._draw_angle(), 0.0)
        self.assertAlmostEqual(b._draw_angle(), 0.0)
        a.angle = 90.0
        b.angle = 90.0
        self.assertAlmostEqual(a._draw_angle(), -90.0)
        self.assertAlmostEqual(b._draw_angle(), -90.0)

    def test_flip_x_toggle_restores_heading(self):
        s = self.track(Sprite(center=(0, 0), size=32, art_angle=0))
        self.assertAlmostEqual(s.angle, 0.0)
        s.flip_x = True
        self.assertAlmostEqual(s.angle, 180.0)
        s.flip_x = False
        self.assertAlmostEqual(s.angle, 0.0)

    def test_flip_x_idempotent(self):
        s = self.track(Sprite(center=(0, 0), size=32, flip_x=True))
        self.assertAlmostEqual(s.angle, 180.0)
        epoch = s._collision_epoch
        s.flip_x = True
        self.assertAlmostEqual(s.angle, 180.0)
        self.assertEqual(s._collision_epoch, epoch)

    def test_rest_heading_and_reset_rotation(self):
        ship = self.track(Sprite(center=(0, 0), size=32, art_angle=90))
        ninja = self.track(Sprite(center=(0, 0), size=32, art_angle=0))
        ninja_flip = self.track(Sprite(center=(0, 0), size=32, art_angle=0, flip_x=True))
        self.assertAlmostEqual(ship.rest_heading, 90.0)
        self.assertAlmostEqual(ninja.rest_heading, 0.0)
        self.assertAlmostEqual(ninja_flip.rest_heading, 180.0)
        ship.rotate_by(30.0)
        ninja.rotate_by(30.0)
        ninja_flip.rotate_by(30.0)
        ship.reset_rotation()
        ninja.reset_rotation()
        ninja_flip.reset_rotation()
        self.assertAlmostEqual(ship.angle, 90.0)
        self.assertAlmostEqual(ninja.angle, 0.0)
        self.assertAlmostEqual(ninja_flip.angle, 180.0)
        self.assertTrue(ninja_flip.flip_x)

    def test_clone_copies_art_angle(self):
        s = self.track(Sprite(center=(0, 0), size=32, art_angle=90))
        s.angle = 45.0
        copy = self.track(s.clone(center=(40, 0)))
        self.assertAlmostEqual(copy.art_angle, 90.0)
        # Clone keeps the live pose (it used to reseed the heading to 90).
        self.assertAlmostEqual(copy.angle, 45.0)
        self.assertAlmostEqual(copy._draw_angle(), s._draw_angle())

    def test_clone_keeps_the_live_pose(self):
        from scena.sprite import AUTO_GROUND
        s = self.track(Sprite(center=(3, 4), size=32, art_angle=90))
        s.flip_x = True
        s.rotate_by(25)
        s.scale = 1.5
        s.tilt = 12.0
        copy = self.track(s.clone())
        for attr in ("angle", "scale", "tilt", "flip_x", "flip_y"):
            self.assertEqual(getattr(copy, attr), getattr(s, attr), attr)
        self.assertEqual(copy._oriented_frame(), s._oriented_frame())
        # clone(scale=) multiplies the copied scale.
        self.assertAlmostEqual(self.track(s.clone(scale=2)).scale, 3.0)
        s.tilt = AUTO_GROUND
        self.assertEqual(self.track(s.clone())._tilt_mode, "auto_ground")

    def test_live_setter_does_not_adjust_rotation(self):
        s = self.track(Sprite(center=(0, 0), size=32, art_angle=90))
        epoch = s._collision_epoch
        s.art_angle = 45.0
        self.assertAlmostEqual(s.art_angle, 45.0)
        self.assertAlmostEqual(s.angle, 90.0)
        self.assertAlmostEqual(s._draw_angle(), 45.0)
        self.assertGreater(s._collision_epoch, epoch)

    def test_ellipse_params_follow_draw_angle(self):
        s = self.track(Sprite(
            center=(0, 0), width=40, height=20, art_angle=90,
        ))
        _cx, _cy, _w, _h, ang = _ellipse_params(s)
        self.assertAlmostEqual(ang, 0.0)
        s.angle = 0.0
        _cx, _cy, _w, _h, ang = _ellipse_params(s)
        self.assertAlmostEqual(ang, -90.0)

    def test_rejects_non_finite_and_non_numeric(self):
        with self.assertRaises(TypeError):
            Sprite(center=(0, 0), size=16, art_angle="up")
        with self.assertRaises(ValueError):
            Sprite(center=(0, 0), size=16, art_angle=float("inf"))

    def test_class_default_and_instance_override(self):
        path = self.tmp("ship.png")
        _write_rect_png(path, 8, 8)

        class Ship(Sprite, source=path, height=16, art_angle=90):
            pass

        a = self.track(Ship(center=(0, 0)))
        self.assertAlmostEqual(a.art_angle, 90.0)
        self.assertAlmostEqual(a.angle, 90.0)
        self.assertAlmostEqual(a._draw_angle(), 0.0)
        b = self.track(Ship(center=(10, 0), art_angle=0))
        self.assertAlmostEqual(b.art_angle, 0.0)
        self.assertAlmostEqual(b.angle, 0.0)
        self.assertAlmostEqual(b._draw_angle(), 0.0)


class TestSpriteFlip(SpriteTestCase):
    def test_ctor_and_property_round_trip(self):
        s = self.track(Sprite(center=(0, 0), size=32, flip_x=True, flip_y=False))
        self.assertTrue(s.flip_x)
        self.assertFalse(s.flip_y)
        epoch = s._collision_epoch
        s.flip_y = True
        self.assertTrue(s.flip_y)
        self.assertGreater(s._collision_epoch, epoch)
        s.flip_x = False
        self.assertFalse(s.flip_x)

    def test_flip_x_moves_offset_hitbox_and_contains(self):
        s = self.track(Sprite(
            center=(0, 0), width=20, height=20, hitbox_shape="rect",
            offset=(10, 0),
        ))
        # Visual / collider centre at +10 before flip.
        cx, cy, *_ = s._oriented_frame()
        self.assertAlmostEqual(cx, 10.0)
        self.assertTrue(s.contains_point(10, 0))
        self.assertFalse(s.contains_point(-10, 0))
        prim = snapshot_shape(s)[0]
        mid_x = 0.5 * (prim.aabb[0] + prim.aabb[2])
        self.assertAlmostEqual(mid_x, 10.0, places=3)

        s.flip_x = True
        cx, cy, *_ = s._oriented_frame()
        self.assertAlmostEqual(cx, -10.0)
        self.assertTrue(s.contains_point(-10, 0))
        self.assertFalse(s.contains_point(10, 0))
        prim = snapshot_shape(s)[0]
        mid_x = 0.5 * (prim.aabb[0] + prim.aabb[2])
        self.assertAlmostEqual(mid_x, -10.0, places=3)

    def test_flip_then_rotate_order(self):
        """``.angle`` is world heading; flip reflects ``art'`` in draw."""
        s = self.track(Sprite(
            center=(0, 0), width=20, height=20, hitbox_shape="rect",
            offset=(10, 0), flip_x=True,
        ))
        self.assertAlmostEqual(s.angle, 180.0)
        s.angle = 90.0
        self.assertAlmostEqual(s._draw_angle(), -90.0)
        cx, cy, *_ = s._oriented_frame()
        self.assertAlmostEqual(cx, 0.0, places=4)
        self.assertAlmostEqual(cy, 10.0, places=4)
        s.flip_x = False
        self.assertAlmostEqual(s.angle, 90.0)
        self.assertAlmostEqual(s._draw_angle(), 90.0)
        cx, cy, *_ = s._oriented_frame()
        self.assertAlmostEqual(cx, 0.0, places=4)
        self.assertAlmostEqual(cy, 10.0, places=4)

    def test_flip_reflects_auto_ellipses_without_rebake(self):
        from scena.atlas import _AUTO_CACHE, reset_atlas_caches

        sh = Sheet(media("shooter", "sheet.xml"))   # plus-shaped Kenney laser frame
        reset_atlas_caches()
        s = self.track(Sprite(sh, frame="laserRed09.png", center=(0, 0), height=48, hitbox_shape="auto"))
        s.collidable = True
        self.assertEqual(len(s._hitbox_ellipses), 2)
        before = [(float(nx), float(ny)) for nx, ny, *_ in s._hitbox_ellipses]
        n_cache = len(_AUTO_CACHE)
        specs0 = s._collision_specs()
        xs0 = sorted(p[1] for p in specs0)

        s.flip_x = True
        self.assertEqual(len(_AUTO_CACHE), n_cache)
        # Local bake unchanged; world specs reflect.
        after = [(float(nx), float(ny)) for nx, ny, *_ in s._hitbox_ellipses]
        self.assertEqual(before, after)
        specs1 = s._collision_specs()
        xs1 = sorted(p[1] for p in specs1)
        self.assertEqual(len(xs0), len(xs1))
        for a, b in zip(xs0, reversed([-x for x in xs1])):
            self.assertAlmostEqual(a, b, places=3)

    def test_clone_copies_live_flip(self):
        path = self.tmp("flip.png")
        _write_rect_png(path, 8, 8)

        class Face(Sprite, source=path, height=16, flip_x=False):
            pass

        src = self.track(Face(center=(0, 0)))
        self.assertFalse(src.flip_x)
        src.flip_x = True
        copy = self.track(src.clone(center=(40, 0)))
        self.assertTrue(copy.flip_x)
        self.assertFalse(copy.flip_y)


class TestSpriteClassDefaults(SpriteTestCase):
    def test_class_source_and_height(self):
        path = self.tmp("shot.png")
        _write_rect_png(path, 8, 8)

        class Shot(Sprite, source=path, height=18):
            pass

        a = self.track(Shot(center=(0, 0)))
        b = self.track(Sprite(path, height=18, center=(10, 0)))
        self.assertIs(a.sheet, b.sheet)
        self.assertAlmostEqual(float(a.height), 18.0)
        self.assertFalse(a._placeholder)

    def test_instance_source_wins(self):
        a_path = self.tmp("a.png")
        b_path = self.tmp("b.png")
        _write_rect_png(a_path, 8, 8, skia.ColorRED)
        _write_rect_png(b_path, 8, 8, skia.ColorBLUE)

        class Shot(Sprite, source=a_path, height=18):
            pass

        other = self.track(Shot(b_path, center=(0, 0)))
        plain = self.track(Sprite(b_path, height=18, center=(10, 0)))
        self.assertIs(other.sheet, plain.sheet)
        self.assertIsNot(other.sheet.image, self.track(Shot(center=(20, 0))).sheet.image)

    def test_frame_omit_vs_explicit(self):
        path = self.tmp("strip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)

        sheet = Sheet(path, cols=4)

        class Cell(Sprite, source=sheet, frame=2, size=16):
            pass

        defaulted = self.track(Cell(center=(0, 0)))
        self.assertEqual(defaulted.frame, 2)
        explicit = self.track(Cell(frame=0, center=(10, 0)))
        self.assertEqual(explicit.frame, 0)

    def test_class_hitbox_from_default(self):
        path = self.tmp("strip.png")
        _write_blob_strip(path, cell=8)

        sheet = Sheet(path, cols=4)

        class Walker(Sprite, source=sheet, hitbox_source="all", size=16):
            pass

        s = self.track(Walker(center=(0, 0)))
        self.assertEqual(s.hitbox.source, "all")

    def test_mro_merge_child_overrides_height(self):
        path = self.tmp("shot.png")
        _write_rect_png(path, 8, 8)

        class Shot(Sprite, source=path, height=18):
            pass

        class BigShot(Shot, height=40):
            pass

        s = self.track(BigShot(center=(0, 0)))
        self.assertAlmostEqual(float(s.height), 40.0)
        self.assertIs(s.sheet, self.track(Sprite(path, height=18, center=(1, 0))).sheet)

    def test_placement_keys_rejected_on_class(self):
        with self.assertRaises(TypeError) as ctx:
            class Bad(Sprite, center=(0, 0)):  # noqa: F841
                pass
        self.assertIn("placement", str(ctx.exception).lower())

        with self.assertRaises(TypeError) as ctx:
            class BadId(Sprite, **{"id": "hero"}):  # noqa: F841
                pass
        self.assertIn("no ids", str(ctx.exception).lower())

    def test_unknown_class_kwargs_raise(self):
        with self.assertRaises(TypeError) as ctx:
            class Bad(Sprite, radius=5):  # noqa: F841
                pass
        msg = str(ctx.exception)
        self.assertIn("radius", msg)
        self.assertIn("Circle", msg)

        with self.assertRaises(TypeError) as ctx:
            class BadAaa(Sprite, aaa=1):  # noqa: F841
                pass
        self.assertIn("aaa", str(ctx.exception))

    def test_class_unknown_frame_is_placeholder(self):
        path = self.tmp("atlas.png")
        _write_grid_png(path, cell=8, cols=2, rows=1)
        meta = self.tmp("atlas.json")
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({
                "frames": {
                    "a.png": {"frame": {"x": 0, "y": 0, "w": 8, "h": 8}},
                    "b.png": {"frame": {"x": 8, "y": 0, "w": 8, "h": 8}},
                }
            }, f)
        sheet = Sheet(path, atlas=meta)

        class Sting(Sprite, source=sheet, frame="wrong_filename.png", height=28, group="sting"):
            pass

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s = self.track(Sting(center=(0, 0)))
        msgs = [w for w in caught if "Unknown frame" in str(w.message)]
        self.assertEqual(len(msgs), 1)
        self.assertTrue(s._placeholder)
        self.assertTrue(s.is_alive)
        self.assertIn("sting", s.group)
        info = skia.ImageInfo.Make(8, 8, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        s._blit_plain(surf.getCanvas())

    def test_clone_keeps_instance_not_class_defaults(self):
        path = self.tmp("shot.png")
        _write_rect_png(path, 8, 8)

        class Shot(Sprite, source=path, height=18, flip_x=False):
            pass

        src = self.track(Shot(center=(0, 0), height=30, flip_x=True))
        self.assertAlmostEqual(float(src.height), 30.0)
        copy = self.track(src.clone(center=(20, 0)))
        self.assertAlmostEqual(float(copy.height), 30.0)
        self.assertTrue(copy.flip_x)
        self.assertIs(copy.sheet, src.sheet)

    def test_sheet_and_frame_default(self):
        path = self.tmp("atlas.png")
        _write_grid_png(path, cell=8, cols=2, rows=1)
        meta = self.tmp("atlas.json")
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({
                "frames": {
                    "a.png": {
                        "frame": {"x": 0, "y": 0, "w": 8, "h": 8},
                        "rotated": False, "trimmed": False,
                        "spriteSourceSize": {"x": 0, "y": 0, "w": 8, "h": 8},
                        "sourceSize": {"w": 8, "h": 8},
                    },
                    "b.png": {
                        "frame": {"x": 8, "y": 0, "w": 8, "h": 8},
                        "rotated": False, "trimmed": False,
                        "spriteSourceSize": {"x": 0, "y": 0, "w": 8, "h": 8},
                        "sourceSize": {"w": 8, "h": 8},
                    },
                },
                "meta": {"image": os.path.basename(path), "size": {"w": 16, "h": 8}},
            }, f)
        # Resolve image next to json for atlas loader.
        sheet = Sheet(path, atlas=meta)

        class Bolt(Sprite, source=sheet, frame="b.png", height=20):
            pass

        s = self.track(Bolt(center=(0, 0)))
        self.assertEqual(s.frame, sheet.frame_index("b.png"))
        override = self.track(Bolt(sheet, frame="a.png", center=(10, 0)))
        self.assertEqual(override.frame, sheet.frame_index("a.png"))


class TestShieldEnvelope(SpriteTestCase):
    """Shield costume envelope: frozen silhouette union, independent of hitbox."""

    def _two_aspect_sheet(self):
        idle = self.tmp("env_idle.png")
        run = self.tmp("env_run.png")
        _write_rect_png(idle, 8, 16)
        _write_rect_png(run, 16, 16)
        sheet = Sheet([idle, run])
        sheet.clip("idle", [idle], fps=1)
        sheet.clip("run", [run], fps=1)
        return sheet

    def test_stable_across_play(self):
        sheet = self._two_aspect_sheet()
        s = self.track(Sprite(sheet, frame=0, center=(0, 0), height=32))
        s.visual = Shield(style="bubble")
        env0 = s._ensure_shield_envelope()
        frame0 = s._shield_envelope_frame()
        _cx, _cy, ow_idle, oh_idle, _ = s._oriented_frame()
        w_idle = float(s.width)
        s.play("run")
        self.assertGreater(float(s.width), w_idle)
        # Playhead design box changed; envelope did not.
        self.assertEqual(s._ensure_shield_envelope(), env0)
        self.assertEqual(s._shield_envelope_frame(), frame0)
        _cx, _cy, ow_run, oh_run, _ = s._oriented_frame()
        self.assertNotEqual((ow_idle, oh_idle), (ow_run, oh_run))

    def test_independent_of_collision(self):
        sheet = self._two_aspect_sheet()
        s = self.track(Sprite(
            sheet, frame=0, center=(0, 0), height=32,
            hitbox_shape="rect", hitbox_source="all",
        ))
        self.assertFalse(s._auto_baked)
        s.visual = Shield(style="vortex")
        self.assertFalse(s._auto_baked)
        self.assertEqual(s._hitbox_boxes, ())
        env = s._ensure_shield_envelope()
        s.collidable = True
        s._ensure_auto_baked()
        self.assertTrue(s._auto_baked)
        self.assertEqual(s._ensure_shield_envelope(), env)
        s.hitbox.scale = 0.5
        s.hitbox.anchor = "bottom"
        s.hitbox.source = "each"
        self.assertEqual(s._ensure_shield_envelope(), env)

    def test_union_covers_larger_pose(self):
        sheet = self._two_aspect_sheet()
        s = self.track(Sprite(sheet, frame=0, center=(0, 0), height=32))
        s.visual = Shield(style="bubble")
        s.shield_scale = 1.0
        _lx, _ly, ew, eh = s._ensure_shield_envelope()
        # Idle design box 16×32; run 32×32 — union width is the larger pose.
        self.assertAlmostEqual(ew, 32.0, places=2)
        self.assertAlmostEqual(eh, 32.0, places=2)

    def test_auto_cache_shared(self):
        from scena.atlas import _AUTO_CACHE

        sheet = self._two_aspect_sheet()
        reset_sprite_caches()
        # Rebuild sheet after cache clear (images were dropped).
        sheet = self._two_aspect_sheet()
        a = self.track(Sprite(sheet, frame=0, center=(0, 0), height=32))
        b = self.track(Sprite(sheet, frame=0, center=(10, 0), height=32))
        n0 = len(_AUTO_CACHE)
        a.visual = Shield(style="bubble")
        n1 = len(_AUTO_CACHE)
        self.assertGreater(n1, n0)
        b.visual = Shield(style="nebula")
        self.assertEqual(len(_AUTO_CACHE), n1)

    def test_electric_still_follows_playhead(self):
        sheet = self._two_aspect_sheet()
        s = self.track(Sprite(sheet, frame=0, center=(0, 0), height=32))
        s.play("idle")
        s.visual = ElectricField()
        _cx, _cy, w0, h0, _ = _ellipse_params(s)
        self.assertAlmostEqual(h0, 32.0, places=2)
        self.assertAlmostEqual(w0, 16.0, places=2)
        s.play("run")
        _cx, _cy, w1, h1, _ = _ellipse_params(s)
        self.assertAlmostEqual(h1, 32.0, places=2)
        self.assertAlmostEqual(w1, 32.0, places=2)
        self.assertGreater(w1, w0)

    def test_shield_scale_multiplies_envelope(self):
        sheet = self._two_aspect_sheet()
        s = self.track(Sprite(sheet, frame=0, center=(0, 0), height=32))
        s.visual = Shield(style="bubble")
        s.shield_scale = 1.0
        _lx, _ly, ew, eh = s._ensure_shield_envelope()
        _cx, _cy, w1, h1, _ = s._shield_envelope_frame()
        self.assertAlmostEqual(w1, ew, places=3)
        self.assertAlmostEqual(h1, eh, places=3)
        s.shield_scale = 1.5
        _cx, _cy, w2, h2, _ = s._shield_envelope_frame()
        self.assertAlmostEqual(w2, ew * 1.5, places=3)
        self.assertAlmostEqual(h2, eh * 1.5, places=3)

    def test_plasma_uses_envelope(self):
        sheet = self._two_aspect_sheet()
        s = self.track(Sprite(sheet, frame=0, center=(0, 0), height=32))
        s.visual = Shield(style="plasma")
        from scena.sprite import _uses_shield_envelope
        self.assertTrue(_uses_shield_envelope(s))
        env0 = s._ensure_shield_envelope()
        s.play("run")
        self.assertEqual(s._ensure_shield_envelope(), env0)
        # Shape hosts never take the costume-envelope UV path (visual alone ≠ Sprite).
        orb = Circle(center=(0, 0), radius=16, visual=Shield(style="bubble"))
        self.assertFalse(_uses_shield_envelope(orb))

    def test_clone_matches_envelope(self):
        sheet = self._two_aspect_sheet()
        s = self.track(Sprite(sheet, frame=0, center=(0, 0), height=32))
        s.visual = Shield(style="bubble")
        s.shield_scale = 1.25
        s.play("run")  # design box matches the union so clone's both-axes copy agrees
        env = s._ensure_shield_envelope()
        frame = s._shield_envelope_frame()
        c = self.track(s.clone())
        self.assertIsInstance(c.visual, Shield)
        self.assertAlmostEqual(c.shield_scale, 1.25)
        self.assertEqual(c._ensure_shield_envelope(), env)
        self.assertEqual(c._shield_envelope_frame()[2:], frame[2:])

    def test_tilt_rotates_envelope_about_anchor(self):
        """Shield oval leans with the art about the hitbox anchor, not its own center."""
        path = self.tmp("shield_tilt.png")
        _write_rect_png(path, 32, 32)
        s = self.track(Sprite(
            path, center=(10.0, 20.0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom",
        ))
        s.visual = Shield(style="bubble")
        s._ensure_auto_baked()
        cx0, cy0, w0, h0, ang0 = s._shield_envelope_frame()
        specs0 = s._collision_specs()
        center0 = (float(s.center.x), float(s.center.y))
        s.tilt = 30.0
        cx, cy, w, h, ang = s._shield_envelope_frame()
        self.assertAlmostEqual(ang, ang0 + 30.0, places=4)
        self.assertAlmostEqual(w, w0, places=4)
        self.assertAlmostEqual(h, h0, places=4)
        self.assertEqual((float(s.center.x), float(s.center.y)), center0)
        self.assertEqual(s._collision_specs(), specs0)
        self.assertAlmostEqual(s._draw_angle(), ang0, places=5)

        px, py = s._tilt_pivot_local()
        lx, ly = cx0 - center0[0], cy0 - center0[1]
        rad = math.radians(30.0)
        c, sn = math.cos(rad), math.sin(rad)
        dx, dy = lx - px, ly - py
        ex = center0[0] + px + c * dx - sn * dy
        ey = center0[1] + py + sn * dx + c * dy
        self.assertAlmostEqual(cx, ex, places=4)
        self.assertAlmostEqual(cy, ey, places=4)
        self.assertGreater(math.hypot(cx - cx0, cy - cy0), 1.0)

        s.angle = 15.0
        specs_tilted = s._collision_specs()
        self.assertAlmostEqual(s._shield_envelope_frame()[4], s._draw_angle() + 30.0, places=4)
        s.tilt = 0
        self.assertEqual(s._collision_specs(), specs_tilted)
        self.assertAlmostEqual(s._shield_envelope_frame()[4], s._draw_angle(), places=4)

    def test_plasma_tilt_matches_shield(self):
        path = self.tmp("shield_plasma.png")
        _write_rect_png(path, 32, 32)
        bubble = self.track(Sprite(
            path, center=(10.0, 20.0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom", visual=Shield(style="bubble"),
        ))
        plasma = self.track(Sprite(
            path, center=(10.0, 20.0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom", visual=Shield(style="plasma"),
        ))
        bubble.tilt = 30.0
        plasma.tilt = 30.0
        for a, b in zip(bubble._shield_envelope_frame(), plasma._shield_envelope_frame()):
            self.assertAlmostEqual(a, b, places=4)

    def test_tilt_ground_seats_envelope(self):
        """Bottom-contact seat shifts the oval with the paint and leaves center put."""
        from scena.collision import TouchingContact
        from scena import Vec2

        path = self.tmp("shield_seat.png")
        _write_rect_png(path, 32, 32)
        s = self.track(Sprite(
            path, center=(10.0, 20.0), height=70,
            hitbox_shape="rect", hitbox_anchor="bottom", visual=Shield(style="bubble"),
        ))
        s._ensure_auto_baked()
        ux, uy, _uw, _uh, uang = s._shield_envelope_frame()
        scx, scy = float(s.center.x), float(s.center.y)
        px, py = s._tilt_pivot_local()
        aabb = s._local_prims_aabb()
        hw = abs(float(s._hitbox_pose_wh()[0]))
        corner_x = aabb[2] * hw
        theta = math.radians(22.0)
        nx, ny = math.sin(theta), -math.cos(theta)
        contact = TouchingContact(
            other=s,
            side="bottom",
            slope_angle=22.0,
            normal=Vec2(nx, ny),
            tangent=Vec2(math.cos(theta), math.sin(theta)),
            point=(scx + corner_x, scy + py),
        )
        s._collision_set_touching(frozenset({"bottom"}), (contact,))
        s.tilt = "ground"
        sx, sy = s._tilt_seat_local(scx, scy)
        self.assertGreater(math.hypot(sx, sy), 1.0)
        lx, ly = ux - scx, uy - scy
        c, sn = math.cos(theta), math.sin(theta)
        dx, dy = lx - px, ly - py
        ex = scx + px + c * dx - sn * dy + sx
        ey = scy + py + sn * dx + c * dy + sy
        cx, cy, _w, _h, ang = s._shield_envelope_frame()
        self.assertAlmostEqual(ang, 22.0, places=4)
        self.assertAlmostEqual(cx, ex, places=4)
        self.assertAlmostEqual(cy, ey, places=4)
        self.assertAlmostEqual(float(s.center.x), scx, places=5)
        self.assertAlmostEqual(float(s.center.y), scy, places=5)
        self.assertAlmostEqual(s._draw_angle(), uang, places=5)
        specs = s._collision_specs()
        s.tilt = 0
        self.assertEqual(s._collision_specs(), specs)


def _skia_aabb(rect) -> tuple:
    return (rect.left(), rect.top(), rect.right(), rect.bottom())


def _envelope_aabb(sprite) -> tuple:
    cx, cy, w, h, ang = sprite._shield_envelope_frame()
    return _aabb_from_oriented(cx, cy, w, h, ang)


class TestShieldFilterBounds(SpriteTestCase):
    """Filter saveLayer / cull: expand dest AABB to the Shield oval only when dest+outset clips it."""

    def setUp(self):
        super().setUp()
        init(width=1000, height=800)
        canvas.reset_view()
        canvas.cull_offscreen = False
        canvas.fx_quality = "high"

    def tearDown(self):
        canvas.cull_offscreen = False
        canvas.reset_view()
        super().tearDown()

    def _opaque_sprite(self, *, height=70, center=(200, 400), **kwargs):
        path = self.tmp("shield_hero.png")
        _write_rect_png(path, 32, 32)
        return self.track(Sprite(path, height=height, center=center, **kwargs))

    def _layer_aabb(self, obj):
        fx = obj.fill_filter
        self.assertIsNotNone(fx)
        self.assertIsNotNone(getattr(fx, "_skia_filter", None))
        eng = ScenaCanvas.get_current()
        return _skia_aabb(eng._layer_bounds_for([obj], fx))

    def _dest_plus_outset(self, obj):
        dest = _approx_draw_aabb(obj)
        self.assertIsNotNone(dest)
        fx = obj.fill_filter
        outset = float(getattr(fx, "_batch_outset", 0.0) or 0.0)
        outset += 0.5 * float(getattr(obj, "line_width", 0) or 0)
        return _pad_aabb(dest, outset)

    def test_approx_draw_aabb_stays_dest(self):
        s = self._opaque_sprite()
        s.visual = Shield(style="vortex")
        dest = _approx_draw_aabb(s)
        env = _envelope_aabb(s)
        self.assertIsNotNone(dest)
        self.assertFalse(_aabb_contains(dest, env))
        cx, cy, w, h, ang = s._oriented_frame()
        self.assertEqual(dest, _aabb_from_oriented(cx, cy, w, h, ang))

    def test_vortex_layer_covers_envelope(self):
        s = self._opaque_sprite()
        s.visual = Shield(style="vortex")
        env = _envelope_aabb(s)
        layer = self._layer_aabb(s)
        dest_pad = self._dest_plus_outset(s)
        self.assertFalse(_aabb_contains(dest_pad, env))
        self.assertTrue(_aabb_contains(layer, env))
        self.assertGreater(layer[2] - layer[0], dest_pad[2] - dest_pad[0])

    def test_bubble_layer_matches_dest_outset(self):
        s = self._opaque_sprite()
        s.visual = Shield(style="bubble")
        layer = self._layer_aabb(s)
        expected = self._dest_plus_outset(s)
        for a, b in zip(layer, expected):
            self.assertAlmostEqual(a, b, places=3)

    def test_bands_layer_matches_dest_outset(self):
        s = self._opaque_sprite()
        s.visual = Shield(style="bands")
        layer = self._layer_aabb(s)
        expected = self._dest_plus_outset(s)
        for a, b in zip(layer, expected):
            self.assertAlmostEqual(a, b, places=3)

    def test_shape_vortex_layer_unchanged(self):
        c = self.track(Circle(center=(200, 400), radius=35))
        c.visual = Shield(style="vortex")
        dest = _approx_draw_aabb(c)
        self.assertIsNotNone(dest)
        expanded = _expand_aabb_for_shield_oval(dest, c, 8.0)
        self.assertEqual(expanded, dest)
        layer = self._layer_aabb(c)
        expected = self._dest_plus_outset(c)
        for a, b in zip(layer, expected):
            self.assertAlmostEqual(a, b, places=3)

    def test_glow_stamp_sprite_unchanged(self):
        s = self._opaque_sprite()
        s.glow = Glow()
        dest = _approx_draw_aabb(s)
        expanded = _expand_aabb_for_shield_oval(dest, s, 40.0)
        self.assertEqual(expanded, dest)
        layer = self._layer_aabb(s)
        expected = self._dest_plus_outset(s)
        for a, b in zip(layer, expected):
            self.assertAlmostEqual(a, b, places=3)

    def test_cull_keeps_vortex_shell_in_view(self):
        # dest+HostGlow pad sits left of x=0; the 1.4× oval still overlaps the view.
        s = self._opaque_sprite(center=(-45, 400))
        s.visual = Shield(style="vortex")
        dest = _approx_draw_aabb(s)
        pad = _filter_outset(s)
        dest_pad = _pad_aabb(dest, pad)
        env = _envelope_aabb(s)
        self.assertLess(dest_pad[2], 0.0)
        self.assertGreater(env[2], 0.0)
        eng = ScenaCanvas.get_current()
        eng.cull_offscreen = True
        layer = eng.registry.layers["default"]
        self.assertTrue(eng._passes_cull(s, layer=layer))


class TestSpriteBlitBlendAndAlpha(SpriteTestCase):
    """Sprite ``.blend`` / ``.alpha`` bake into ``_blit_paint`` at set-time."""

    def _plain_png(self, name="body.png", color=(255, 0, 0, 128)):
        path = self.tmp(name)
        _write_rgba_png(path, 16, 16, color)
        return path

    def _sprite(self, *, color=(255, 0, 0, 128), size=32, center=(32, 32), **kwargs):
        return self.track(Sprite(
            self._plain_png(),
            width=size, height=size, center=center, **kwargs,
        ))

    def _blit_center(self, sprite, dest=skia.ColorBLUE, size=64):
        info = skia.ImageInfo.Make(
            size, size, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType,
        )
        surf = skia.Surface.MakeRaster(info)
        canvas = surf.getCanvas()
        canvas.clear(dest)
        sprite._blit_plain(canvas)
        return _surface_center_rgba(surf)

    def test_default_plain_shares_singleton(self):
        from scena.sprite import _BLIT_PAINT
        s = self._sprite()
        self.assertAlmostEqual(s.alpha, 1.0)
        self.assertIs(s._blit_paint, _BLIT_PAINT)
        self.assertTrue(s._plain_blit)

    def test_blend_string_and_enum_coerce(self):
        from scena.style import BlendMode
        s = self._sprite()
        s.blend = "add"
        self.assertEqual(s.blend, "add")
        other = self._sprite()
        other.blend = s.blend
        self.assertEqual(other.blend, "add")
        s.blend = BlendMode.ADD
        self.assertIs(s._blend, BlendMode.ADD)
        self.assertEqual(s.blend, "add")
        with self.assertRaises(TypeError) as ctx:
            s.blend = "nope"
        msg = str(ctx.exception)
        self.assertIn("add", msg)
        self.assertIn("multiply", msg)

    def test_blend_pixel_composite_add_differs_and_matches_plus(self):
        s = self._sprite()
        normal = self._blit_center(s)
        plus_paint = skia.Paint(AntiAlias=True, BlendMode=skia.BlendMode.kPlus)
        info = skia.ImageInfo.Make(64, 64, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        canvas = surf.getCanvas()
        canvas.clear(skia.ColorBLUE)
        s._blit_image(canvas, plus_paint)
        hand = _surface_center_rgba(surf)
        s.blend = "add"
        added = self._blit_center(s)
        self.assertNotEqual(normal, added)
        self.assertEqual(added, hand)

    def test_blend_reset_restores_singleton(self):
        from scena.sprite import _BLIT_PAINT
        s = self._sprite()
        s.blend = "add"
        self.assertIsNot(s._blit_paint, _BLIT_PAINT)
        self.assertTrue(s._plain_blit)
        s.blend = "normal"
        self.assertIs(s._blit_paint, _BLIT_PAINT)
        self.assertTrue(s._plain_blit)

    def test_blend_alone_stays_plain(self):
        from scena.sprite import _BLIT_PAINT
        from scena.canvas import ScenaCanvas
        if ScenaCanvas.get_current() is None:
            init(width=400, height=300, title="sprite-blend-plain")
        s = self._sprite()
        s.blend = "add"
        self.assertTrue(s._plain_blit)
        self.assertIsNot(s._blit_paint, _BLIT_PAINT)
        self.assertEqual(s._blit_paint.getBlendMode(), skia.BlendMode.kPlus)
        n0 = ScenaCanvas._plain_blit_draws
        ScenaCanvas.get_current()._draw_layer_batched([s])
        self.assertGreater(ScenaCanvas._plain_blit_draws, n0)

    def test_hue_plus_blend_one_paint(self):
        from scena.sprite import _BLIT_PAINT
        s = self._sprite()
        s.hue = HueShift(amount=0.25)
        s.blend = "add"
        p = s._blit_paint
        self.assertIsNot(p, _BLIT_PAINT)
        self.assertIsNotNone(p.getColorFilter())
        self.assertEqual(p.getBlendMode(), skia.BlendMode.kPlus)
        s.hue = None
        self.assertIsNone(s._blit_color_filter)
        self.assertEqual(s._blit_paint.getBlendMode(), skia.BlendMode.kPlus)
        s.hue = HueShift(amount=0.2)
        s.blend = "normal"
        self.assertIsNotNone(s._blit_paint.getColorFilter())
        self.assertEqual(s._blit_paint.getBlendMode(), skia.BlendMode.kSrcOver)

    def test_live_hue_applies_blend_and_alpha(self):
        s = self._sprite()
        s.hue = HueShift(amount=0.15, live=True)
        self.assertIsNotNone(s._blit_hue_live)
        self.assertFalse(s._plain_blit)
        s.blend = "add"
        s.alpha = 0.5
        paint = skia.Paint(AntiAlias=True)
        s._apply_blit_paint_extras(paint)
        self.assertEqual(paint.getBlendMode(), skia.BlendMode.kPlus)
        self.assertAlmostEqual(paint.getAlphaf(), 0.5, places=5)
        info = skia.ImageInfo.Make(64, 64, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        s._blit_hue_sksl(surf.getCanvas())  # must not skip extras (no crash)

    def test_look_like_copies_blend_and_alpha(self):
        from scena.sprite import _BLIT_PAINT
        src = self._sprite()
        dst = self._sprite(color=(0, 255, 0, 255))
        src.blend = "add"
        src.alpha = 0.3
        dst.look_like(src)
        self.assertEqual(dst.blend, "add")
        self.assertAlmostEqual(dst.alpha, 0.3)
        self.assertIsNot(dst._blit_paint, _BLIT_PAINT)
        self.assertEqual(dst._blit_paint.getBlendMode(), skia.BlendMode.kPlus)
        src.blend = "normal"
        src.alpha = 1.0
        dst.look_like(src)
        self.assertIs(dst._blit_paint, _BLIT_PAINT)

    def test_visual_identity_restores_body_blit_leaves_alpha(self):
        from scena.sprite import _BLIT_PAINT
        from scena.style import BlendMode
        s = self._sprite()
        s.alpha = 0.4
        s.visual = Halo()
        self.assertFalse(s._plain_blit)
        s.visual = None
        self.assertTrue(s._plain_blit)
        self.assertIs(s._blend, BlendMode.NORMAL)
        self.assertEqual(s._blit_paint.getBlendMode(), skia.BlendMode.kSrcOver)
        self.assertAlmostEqual(s.alpha, 0.4)
        s.alpha = 1.0
        self.assertIs(s._blit_paint, _BLIT_PAINT)

    def test_svg_inherits_blend_and_alpha(self):
        from scena.sprite import _BLIT_PAINT
        markup = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
            '<circle cx="20" cy="20" r="16" fill="#f00"/>'
            "</svg>"
        )
        s = self.track(Svg(markup, height=32, center=(0, 0)))
        self.assertIs(s._blit_paint, _BLIT_PAINT)
        s.blend = "add"
        self.assertTrue(s._plain_blit)
        self.assertEqual(s._blit_paint.getBlendMode(), skia.BlendMode.kPlus)
        out = s.set_alpha(0.5)
        self.assertIs(out, s)
        self.assertAlmostEqual(s.alpha, 0.5)
        self.assertAlmostEqual(s._blit_paint.getAlphaf(), 0.5, places=5)

    def test_alpha_write_read_and_set_alpha_returns_self(self):
        s = self._sprite()
        s.alpha = 0.5
        self.assertAlmostEqual(s.alpha, 0.5)
        out = s.set_alpha(0.4)
        self.assertIs(out, s)
        self.assertAlmostEqual(s.alpha, 0.4)

    def test_alpha_clamp(self):
        s = self._sprite()
        s.alpha = 1.5
        self.assertAlmostEqual(s.alpha, 1.0)
        s.alpha = -1
        self.assertAlmostEqual(s.alpha, 0.0)

    def test_set_alpha_no_crash_regression(self):
        s = self.track(Sprite(self._plain_png("x.png"), size=16, center=(0, 0)))
        s.set_alpha(0.5)
        self.assertAlmostEqual(s.alpha, 0.5)

    def test_alpha_not_ink(self):
        from scena.entity import _INK_RESERVED
        from scena.state import Attribute
        self.assertIn("alpha", _INK_RESERVED)
        s = self._sprite()
        s.alpha = 0.5
        ink = getattr(s, "_ink", None) or {}
        self.assertNotIn("alpha", ink)
        # ``alpha`` links since the appearance links: through the setter, never
        # into ink (tests/test_paint_flag_links.py).
        s["alpha"] @= Attribute(0.2)
        self.assertAlmostEqual(s.alpha, 0.2)
        self.assertNotIn("alpha", getattr(s, "_ink", None) or {})
        s["alpha"].unlink()
        e = Entity()
        self.addCleanup(e.destroy)
        with self.assertRaises(AttributeError) as ctx:
            e.alpha = 5
        self.assertIn("has no field 'alpha' (a Sprite field)", str(ctx.exception))
        ink_e = getattr(e, "_ink", None) or {}
        self.assertNotIn("alpha", ink_e)
        with self.assertRaises(AttributeError) as ctx:
            e["alpha"] @= Attribute(1)
        self.assertIn("has no field 'alpha' (a Sprite field)", str(ctx.exception))

    def test_alpha_pixel_and_paint(self):
        s = self._sprite(color=(255, 0, 0, 255))
        full = self._blit_center(s)
        s.alpha = 0.5
        self.assertAlmostEqual(s._blit_paint.getAlphaf(), 0.5, places=5)
        half = self._blit_center(s)
        self.assertGreater(full[0], half[0])
        self.assertGreater(full[0] - half[0], 20)

    def test_alpha_reset_and_plain_stays(self):
        from scena.sprite import _BLIT_PAINT
        s = self._sprite()
        s.alpha = 0.5
        self.assertIsNot(s._blit_paint, _BLIT_PAINT)
        self.assertTrue(s._plain_blit)
        s.alpha = 1.0
        self.assertIs(s._blit_paint, _BLIT_PAINT)
        self.assertTrue(s._plain_blit)

    def test_alpha_plus_blend_one_paint(self):
        from scena.sprite import _BLIT_PAINT
        s = self._sprite()
        s.alpha = 0.5
        s.blend = "add"
        p = s._blit_paint
        self.assertIsNot(p, _BLIT_PAINT)
        self.assertEqual(p.getBlendMode(), skia.BlendMode.kPlus)
        self.assertAlmostEqual(p.getAlphaf(), 0.5, places=5)

    def test_alpha_plus_hue_one_paint(self):
        s = self._sprite()
        s.hue = HueShift(amount=0.3)
        s.alpha = 0.5
        p = s._blit_paint
        self.assertIsNotNone(p.getColorFilter())
        self.assertAlmostEqual(p.getAlphaf(), 0.5, places=5)
        s.hue = None
        self.assertIsNone(s._blit_paint.getColorFilter())
        self.assertAlmostEqual(s._blit_paint.getAlphaf(), 0.5, places=5)
        s.hue = HueShift(amount=0.2)
        s.alpha = 1.0
        self.assertIsNotNone(s._blit_paint.getColorFilter())
        self.assertGreaterEqual(s._blit_paint.getAlphaf(), 1.0 - 1e-6)

    def test_alpha_composes_with_fade_out(self):
        from scena.transients import compose_draw_mods, _now, set_now_fn
        s = self._sprite(color=(255, 0, 0, 255))
        s.alpha = 0.5
        s.fade_out(0.2)
        now = _now()
        # Pin the clock: draw() reads it, and under a loaded tier the fade
        # moved on between here and the draw (gate WP14: 9 > 8 on one channel).
        set_now_fn(lambda: now)
        self.addCleanup(set_now_fn, None)
        s._tx_state.life.t0 = now - 0.1
        mods = compose_draw_mods(s, now=now)
        self.assertIsNotNone(mods)
        self.assertAlmostEqual(mods.alpha_mul, 0.5, places=5)
        self.assertAlmostEqual(s._blit_paint.getAlphaf(), 0.5, places=5)
        self.assertAlmostEqual(mods.alpha_mul * s._blit_paint.getAlphaf(), 0.25, places=5)

        baked = self._sprite(color=(255, 0, 0, 255), center=(32, 32))
        baked.alpha = 0.25
        expected = self._blit_center(baked)

        info = skia.ImageInfo.Make(64, 64, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        canvas = surf.getCanvas()
        canvas.clear(skia.ColorBLUE)
        s.move_to(32, 32)
        s.draw(canvas)
        got = _surface_center_rgba(surf)
        for a, b in zip(got, expected):
            self.assertLessEqual(abs(a - b), 8)

    def test_clone_copies_alpha(self):
        s = self._sprite()
        s.alpha = 0.3
        s.blend = "add"
        c = self.track(s.clone())
        self.assertAlmostEqual(c.alpha, 0.3)
        self.assertEqual(c.blend, "add")

    def test_shape_set_alpha_unchanged(self):
        c = self.track(Circle(center=(0, 0), radius=10, color="red"))
        out = c.set_alpha(0.5)
        self.assertIs(out, c)
        self.assertAlmostEqual(c.fill.alpha, 0.5)
        self.assertFalse(hasattr(c, "_alpha"))


class TestSpriteGrayStamp(SpriteTestCase):
    """``sprite.gray`` / ``Grayscale``: a blit ColorFilter composed over hue."""

    _plain_png = TestSpriteBlitBlendAndAlpha._plain_png
    _blit_center = TestSpriteBlitBlendAndAlpha._blit_center

    def _red(self, **kw):
        path = self.tmp("red.png")
        _write_rgba_png(path, 16, 16, (220, 30, 30, 255))
        return self.track(Sprite(path, width=32, height=32, center=(32, 32), **kw))

    def test_true_is_fully_gray_and_stays_plain(self):
        s = self._red()
        s.gray = True
        self.assertIsInstance(s.gray, Grayscale)
        self.assertEqual(s.gray.amount, 1.0)
        self.assertTrue(s._plain_blit)
        r, g, b, a = self._blit_center(s)
        self.assertLessEqual(max(r, g, b) - min(r, g, b), 2)
        self.assertEqual(a, 255)

    def test_half_is_between(self):
        s = self._red()
        r0, g0, _, _ = self._blit_center(s)
        s.gray = 0.5
        r, g, b, _ = self._blit_center(s)
        s.gray = True
        rg, gg, _, _ = self._blit_center(s)
        self.assertLess(rg, r)
        self.assertLess(r, r0)
        self.assertGreater(g, g0)
        self.assertLess(g, gg)

    def test_off_spellings(self):
        s = self._red()
        for off in (None, False, 0, 0.0):
            s.gray = True
            s.gray = off
            self.assertIsNone(s.gray)
            self.assertIsNone(s._blit_gray_cf)
        from scena.sprite import _BLIT_PAINT
        self.assertIs(s._blit_paint, _BLIT_PAINT)

    def test_off_spelling_after_a_tiny_amount_was_interned(self):
        # Deep-tier serial find: an earlier module built Grayscale(1e-5); the
        # cache keys on round(amount, 4), so Grayscale(0) returned that object
        # (amount 1e-5) and ``sprite.gray = 0`` stayed on.
        tiny = Grayscale(0.00001)
        self.assertIs(Grayscale(0), tiny)
        self.assertEqual(tiny.amount, 0.0)
        s = self._red()
        s.gray = 0
        self.assertIsNone(s.gray)

    def test_interned_amount_does_not_depend_on_creation_order(self):
        for first, second in ((0.50004, 0.5), (0.99996, 1.0), (0.12341, 0.1234)):
            a, b = Grayscale(first), Grayscale(second)
            self.assertIs(a, b)
            self.assertEqual(a.amount, round(second, 4))

    def test_composes_with_static_hue(self):
        s = self._red()
        s.hue = HueShift(amount=0.33)
        s.gray = True
        self.assertIsInstance(s.hue, HueShift)
        r, g, b, _ = self._blit_center(s)
        self.assertLessEqual(max(r, g, b) - min(r, g, b), 2)
        s.gray = None
        r, g, b, _ = self._blit_center(s)
        self.assertGreater(max(r, g, b) - min(r, g, b), 50)   # hue survives

    def test_live_hue_keeps_gray(self):
        s = self._red()
        s.gray = True
        s.hue = HueShift(amount=0.15, live=True)
        paint = skia.Paint(AntiAlias=True)
        s._apply_blit_paint_extras(paint)
        self.assertIsNotNone(paint.getColorFilter())

    def test_gray_with_alpha_and_blend(self):
        s = self._red()
        s.alpha = 0.5
        s.gray = True
        s.blend = "add"
        p = s._blit_paint
        self.assertIsNotNone(p.getColorFilter())
        self.assertAlmostEqual(p.getAlphaf(), 0.5, places=5)
        s.gray = None
        self.assertIsNone(s._blit_paint.getColorFilter())

    def test_clone_and_look_like_copy_gray(self):
        s = self._red()
        s.gray = 0.5
        c = self.track(s.clone())
        self.assertIs(c.gray, s.gray)
        self.assertIsNotNone(c._blit_gray_cf)
        other = self._red()
        other.look_like(s)
        self.assertIs(other.gray, s.gray)
        self.assertIsNotNone(other._blit_gray_cf)

    def test_interned(self):
        self.assertIs(Grayscale(0.5), Grayscale(0.5))
        self.assertIsNot(Grayscale(0.5), Grayscale(1))

    def test_bad_values(self):
        s = self._red()
        with self.assertRaises(ValueError):
            s.gray = 1.5
        with self.assertRaises((ValueError, TypeError)):
            s.gray = -0.2
        with self.assertRaisesRegex(TypeError, "sprite.gray expected"):
            s.gray = "yes"
        with self.assertRaisesRegex(TypeError, "is a stamp"):
            s.visual = Grayscale()

    def test_shapes_and_text_refuse(self):
        c = self.track(Circle(center=(0, 0), radius=4))
        with self.assertRaisesRegex(TypeError, "Sprite-only"):
            c.gray = True
        from scena import Text
        t = self.track(Text("x", center=(0, 0)))
        with self.assertRaisesRegex(TypeError, "Text does not support .gray"):
            t.gray = True
        c.gray = None   # off is always fine

    def test_svg_and_subclasses_accept(self):
        class Ship(Sprite):
            pass
        svg = self.track(Svg(
            '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">'
            '<rect width="8" height="8" fill="red"/></svg>'))
        svg.gray = True
        ship = self.track(Ship(self._plain_png()))
        ship.gray = True
        self.assertIsNotNone(svg._blit_gray_cf)
        self.assertIsNotNone(ship._blit_gray_cf)

    def test_gray_is_not_linkable_ink(self):
        s = self._red()
        with self.assertRaises(AttributeError):
            s["gray"]


class TestHitboxRefinements(SpriteTestCase):
    """``hitbox_from`` clip scope, kind lock, and numeric anchor."""

    def _sheet(self, blobs=None):
        path = self.tmp("cells.png")
        _write_blob_strip(path, cell=32, blobs=blobs)
        return Sheet(path, cols=len(blobs) if blobs else 4)

    def test_all_unions_registered_clips_only(self):
        sheet = self._sheet()
        sheet.clip("enemy", [0, 1], fps=8)
        sheet.clip("shot", [2], fps=8)
        s = self.track(Sprite(
            sheet, frame=0, center=(0, 0), size=32, hitbox_shape="rect", hitbox_source="all",
        ))
        self.assertEqual(s._hitbox_from_indices(), (0, 1, 2))
        self.assertNotIn(3, s._hitbox_from_indices())

    def test_all_with_no_clips_is_construct_frame(self):
        sheet = self._sheet()
        s = self.track(Sprite(
            sheet, frame=2, center=(0, 0), size=32, hitbox_shape="rect", hitbox_source="all",
        ))
        self.assertEqual(s.hitbox.source, "all")
        self.assertEqual(s._hitbox_from_indices(), (2,))

    def test_tuple_of_clips_unions_only_those(self):
        sheet = self._sheet()
        sheet.clip("a", [0], fps=8)
        sheet.clip("b", [1, 2], fps=8)
        sheet.clip("c", [3], fps=8)
        s = self.track(Sprite(
            sheet, frame=0, center=(0, 0), size=32, hitbox_shape="rect",
            hitbox_source=("a", "b"),
        ))
        self.assertEqual(s.hitbox.source, ("a", "b"))
        self.assertEqual(s._hitbox_from_indices(), (0, 1, 2))
        with self.assertRaises(ValueError):
            s.hitbox.source = ()
        with self.assertRaises(ValueError):
            s.hitbox.source = ("missing",)
        with self.assertRaises(ValueError):
            s.hitbox.source = (1, 2)

    def test_clip_rebakes_on_switch_not_on_tick(self):
        idle = self.tmp("idle.png")
        swim = self.tmp("swim.png")
        _write_rect_png(idle, 16, 32)
        _write_rect_png(swim, 40, 16)
        sheet = Sheet([idle, swim])
        sheet.clip("walk", [idle], fps=8)
        sheet.clip("swim", [swim], fps=8)
        s = self.track(Sprite(
            sheet, frame=0, center=(0, 0), height=32,
            hitbox_shape="rect", hitbox_source="clip",
        ))
        s.collidable = True
        self.assertEqual(s._hitbox_from_indices(), (0,))
        fp = s._collision_specs()
        s.play("walk")
        self.assertEqual(s._collision_specs(), fp)
        held = s._collision_epoch
        for _ in range(4):
            clock.advance(0.05)
            s._sync_auto_hitbox_frame()
        self.assertEqual(s._collision_epoch, held)
        held_fp = s._collision_specs()
        s.play("swim")
        self.assertGreater(s._collision_epoch, held)
        self.assertNotEqual(s._collision_specs(), held_fp)
        after = s._collision_epoch
        swim_fp = s._collision_specs()
        for _ in range(4):
            clock.advance(0.05)
            s._sync_auto_hitbox_frame()
            self.assertEqual(s._collision_specs(), swim_fp)
        self.assertEqual(s._collision_epoch, after)

    def test_clip_without_playback_is_construct_frame(self):
        sheet = self._sheet()
        sheet.clip("walk", [1, 2], fps=8)
        s = self.track(Sprite(
            sheet, frame=0, center=(0, 0), size=32, hitbox_source="clip",
        ))
        self.assertIsNone(s._play_name)
        self.assertEqual(s._hitbox_from_indices(), (0,))

    def test_clone_copies_clip_and_rebakes_independently(self):
        idle = self.tmp("idle.png")
        swim = self.tmp("swim.png")
        _write_rect_png(idle, 16, 32)
        _write_rect_png(swim, 40, 16)
        sheet = Sheet([idle, swim])
        sheet.clip("walk", [idle], fps=8)
        sheet.clip("swim", [swim], fps=8)
        a = self.track(Sprite(
            sheet, frame=0, center=(0, 0), height=32,
            hitbox_shape="rect", hitbox_source="clip",
        ))
        a.collidable = True
        a.play("walk")
        b = self.track(a.clone(center=(80, 0)))
        self.assertEqual(b.hitbox.source, "clip")
        b.collidable = True
        b.play("swim")
        self.assertEqual(a._hitbox_from_indices(), (0,))
        self.assertEqual(b._hitbox_from_indices(), (1,))
        self.assertNotEqual(a._collision_specs(), b._collision_specs())

    def test_each_locks_kind_across_frames(self):
        import scena.atlas as atlas

        path = self.tmp("lock.png")
        _write_blob_strip(path, cell=32)
        sheet = Sheet(path, cols=4, fps=8)
        calls = []
        orig = atlas._choose_auto_collider

        def wrapped(mask, force_kind=None):
            calls.append(force_kind)
            if force_kind is None:
                forced = "circle" if len(calls) == 1 else "poly"
                return orig(mask, force_kind=forced)
            return orig(mask, force_kind=force_kind)

        atlas._choose_auto_collider = wrapped
        try:
            s = self.track(Sprite(
                sheet, center=(0, 0), size=32,
                hitbox_shape="auto", hitbox_source="each",
            ))
            s.collidable = True
            self.assertEqual(calls[0], None)
            self.assertEqual(s._hitbox_locked_kind, "circle")
            kind0 = snapshot_shape(s)[0].kind
            clock.advance(0.125)
            s._sync_auto_hitbox_frame()
            self.assertGreaterEqual(len(calls), 2)
            self.assertEqual(calls[1], "circle")
            self.assertEqual(snapshot_shape(s)[0].kind, kind0)
            self.assertEqual(s._hitbox_locked_kind, "circle")
            s.hitbox.shape = "circle"
            self.assertIsNone(s._hitbox_locked_kind)
        finally:
            atlas._choose_auto_collider = orig

    def test_named_hull_does_not_lock_or_flip(self):
        import scena.atlas as atlas

        path = self.tmp("hull.png")
        _write_blob_strip(path, cell=32)
        sheet = Sheet(path, cols=4, fps=8)
        calls = []
        orig = atlas._choose_auto_collider

        def wrapped(mask, force_kind=None):
            calls.append(force_kind)
            return orig(mask, force_kind=force_kind)

        atlas._choose_auto_collider = wrapped
        try:
            s = self.track(Sprite(
                sheet, center=(0, 0), size=32,
                hitbox_shape="hull", hitbox_source="each",
            ))
            s.collidable = True
            clock.advance(0.125)
            s._sync_auto_hitbox_frame()
            self.assertTrue(calls)
            self.assertTrue(all(c == "poly" for c in calls))
            self.assertIsNone(s._hitbox_locked_kind)
            # The named hull stays a hull spec. Its prim is an AABB only when
            # the hull is exactly an axis-aligned rectangle (Collision Design,
            # "Axis-aligned hulls"); this blob's is.
            self.assertTrue(all(spec[0] == "poly" for spec in s._collision_specs()))
            prim = snapshot_shape(s)[0]
            hull = s._collision_specs()[0][1]
            if prim.kind == PrimKind.AABB:
                xs = sorted({round(x, 6) for x, _ in hull})
                ys = sorted({round(y, 6) for _, y in hull})
                self.assertEqual((len(hull), len(xs), len(ys)), (4, 2, 2))
            else:
                self.assertEqual(prim.kind, PrimKind.POLY)
        finally:
            atlas._choose_auto_collider = orig

    def test_anchor_presets_match_numeric_pairs(self):
        from scena.sprite import _HITBOX_ANCHOR_XY, _anchor_on_aabb

        box = (0.0, 0.0, 10.0, 20.0)
        for name, pair in _HITBOX_ANCHOR_XY.items():
            self.assertEqual(
                _anchor_on_aabb(*box, name),
                _anchor_on_aabb(*box, pair),
            )
        mid = _anchor_on_aabb(*box, (-0.5, 0.0))
        center = _anchor_on_aabb(*box, "center")
        left = _anchor_on_aabb(*box, "left")
        self.assertAlmostEqual(mid[0], 0.5 * (center[0] + left[0]), places=6)
        self.assertAlmostEqual(mid[1], center[1], places=6)
        extra = _anchor_on_aabb(*box, (2.0, 0.0))
        self.assertGreater(extra[0], _anchor_on_aabb(*box, "right")[0])

    def test_numeric_anchor_round_trips_and_pins_like_bottom(self):
        path = self.tmp("padded.png")
        _write_padded_png(path, canvas_w=64, canvas_h=64, blob=(20, 8, 24, 40))
        s = self.track(Sprite(
            path, center=(0, 0), width=64, height=64,
            hitbox_shape="rect", hitbox_anchor=(0, -1),
        ))
        self.assertEqual(s.hitbox.anchor, (0.0, -1.0))
        miny0 = snapshot_shape(s)[0].aabb[1]
        s.hitbox.scale = (0.5, 0.5)
        self.assertAlmostEqual(snapshot_shape(s)[0].aabb[1], miny0, places=3)
        s.hitbox.anchor = "bottom"
        self.assertEqual(s.hitbox.anchor, "bottom")
        pivot = s._tilt_pivot_local()
        s.hitbox.anchor = (0.0, -1.0)
        self.assertEqual(s._tilt_pivot_local(), pivot)
        with self.assertRaises(TypeError):
            s.hitbox.anchor = True
        with self.assertRaises(TypeError):
            s.hitbox.anchor = (1.0,)
        with self.assertRaises(ValueError):
            s.hitbox.anchor = "center-left"

    def test_left_anchor_pins_to_bake_not_wider_sheet(self):
        """A narrow frame is not glued to a wider clip's left edge."""
        narrow = self.tmp("narrow.png")
        wide = self.tmp("wide.png")
        _write_rect_png(narrow, 32, 64)
        _write_rect_png(wide, 128, 64)
        sheet = Sheet([narrow, wide])
        sheet.clip("wide", [1], fps=1)
        s = self.track(Sprite(
            sheet, frame=0, center=(0, 0), height=64,
            hitbox_shape="rect", hitbox_source=0, hitbox_anchor="left",
        ))
        s._ensure_auto_baked()
        minx = snapshot_shape(s)[0].aabb[0]
        half = 0.5 * abs(float(s.width))
        self.assertAlmostEqual(minx, -half, places=2)
        self.assertGreater(minx, -half - 2.0)

    def test_track_sprite_follows_frame_and_pose(self):
        from scena.track import Track

        path = self.tmp("sil.png")
        _write_blob_strip(path, cell=32)
        sheet = Sheet(path, cols=4, fps=8)
        s = self.track(Sprite(sheet, center=(10, 20), size=32))
        outline = self.track(Track(s))
        again = self.track(Track(s))
        self.assertIsNot(again, outline)
        self.assertFalse(outline.collidable)
        outline._ensure_samples()
        self.assertGreaterEqual(len(outline._xs), 3)
        p0 = outline.at(0.0)
        s.center = (40, 20)
        p1 = outline.at(0.0)
        self.assertAlmostEqual(p1[0] - p0[0], 30.0, places=1)
        key0 = outline._geom_key()
        clock.advance(0.125)
        key1 = outline._geom_key()
        self.assertNotEqual(key0, key1)

    def test_silhouette_sugar_is_gone(self):
        # ``Track(sprite)`` is the one spelling of the live outline.
        path = self.tmp("sil.png")
        _write_rect_png(path, 24, 24)
        s = self.track(Sprite(path, center=(0, 0), size=24))
        with self.assertRaises(AttributeError):
            s.silhouette

    def test_destroy_sprite_freezes_silhouette(self):
        from scena.track import Track

        path = self.tmp("sil.png")
        _write_rect_png(path, 24, 24)
        s = self.track(Sprite(path, center=(0, 0), size=24))
        outline = self.track(Track(s))
        outline._ensure_samples()
        n = len(outline._xs)
        self.assertGreaterEqual(n, 3)
        s.destroy()
        self.assertIsNone(outline._live_source())
        outline._ensure_samples()
        self.assertTrue(outline._source_frozen)
        self.assertEqual(len(outline._xs), n)


class TestHitboxProposalEdges(SpriteTestCase):
    """Edge cases from the sprite hitbox bugfix pass (B1-B4, B6-B11, B13; B5 excluded).

    Each test pins a fixed bug; B8/B12 guards prove no-change. Design:
    Collision Design — Sprite colliders; Sprite Design — Auto hitbox.
    """

    def test_b1_circle_stretch_emits_ellipse(self):
        path = self.tmp("sq.png")
        _write_rect_png(path, 64, 64)
        s = self.track(Sprite(path, center=(0, 0), width=100, height=40, hitbox_shape="circle"))
        specs = s._collision_specs()
        self.assertEqual(specs[0][0], "ellipse", f"B1: stretched circle should be ellipse, got {specs}")
        rx, ry = float(specs[0][3]), float(specs[0][4])
        self.assertLess(ry, 30.0, f"B1: ry {ry} should match pixel truth ~22.5, not circle r ~56")

    def test_b1_circle_unstretched_stays_circle(self):
        path = self.tmp("sq.png")
        _write_rect_png(path, 64, 64)
        s = self.track(Sprite(path, center=(0, 0), size=64, hitbox_shape="circle"))
        specs = s._collision_specs()
        self.assertEqual(specs[0][0], "circle")

    def test_b2_rotated_ellipse_aabb_uses_pose_aspect(self):
        path = self.tmp("sq.png")
        _write_rect_png(path, 64, 64)
        s = self.track(Sprite(path, center=(0, 0), width=100, height=40, hitbox_shape="rect"))
        s._ensure_auto_baked()
        ang = math.radians(30.0)
        s._hitbox_boxes = ()
        s._hitbox_circle = None
        s._hitbox_circles = ()
        s._hitbox_poly = ()
        s._hitbox_ellipses = ((0.0, 0.0, 0.2, 0.1, ang),)
        s._hitbox_ellipse = (0.0, 0.0, 0.2, 0.1, ang)
        s._snapshot_hitbox_base()
        s._hitbox_scale = (1.0, 1.0)
        s._apply_hitbox_shaping()
        aabb = s._local_prims_aabb()
        w, h = s._hitbox_pose_wh()
        rx, ry = 0.2, 0.1
        c, sn = math.cos(ang), math.sin(ang)
        ex_true = math.sqrt((rx * c) ** 2 + (ry * (h / w) * sn) ** 2)
        ey_true = math.sqrt((rx * (w / h) * sn) ** 2 + (ry * c) ** 2)
        self.assertAlmostEqual((aabb[2] - aabb[0]) / 2, ex_true, places=6,
                               msg=f"B2: ex {aabb} vs true {ex_true}")
        self.assertAlmostEqual((aabb[3] - aabb[1]) / 2, ey_true, places=6,
                               msg=f"B2: ey {aabb} vs true {ey_true}")

    def test_b3_uniform_mixed_ellipses_scaled(self):
        path = self.tmp("sq.png")
        _write_rect_png(path, 64, 64)
        s = self.track(Sprite(path, center=(0, 0), width=64, height=64, hitbox_shape="rect"))
        s._ensure_auto_baked()
        s._hitbox_circles = ((0.0, 0.0, 0.1),)
        s._hitbox_circle = (0.0, 0.0, 0.1)
        s._hitbox_ellipses = ((0.0, 0.0, 0.1, 0.05, 0.0),)
        s._hitbox_ellipse = (0.0, 0.0, 0.1, 0.05, 0.0)
        s._snapshot_hitbox_base()
        s._hitbox_scale = (0.5, 0.5)
        s._apply_hitbox_shaping()
        got = {tuple(round(v, 6) for v in e) for e in s._hitbox_ellipses}
        self.assertIn((0.0, 0.0, 0.05, 0.025, 0.0), got,
                      f"B3 uniform: original ellipse unscaled, got {s._hitbox_ellipses}")

    def test_b3_nonuniform_mixed_preserves_both(self):
        path = self.tmp("sq.png")
        _write_rect_png(path, 64, 64)
        s = self.track(Sprite(path, center=(0, 0), width=64, height=64, hitbox_shape="rect"))
        s._ensure_auto_baked()
        s._hitbox_circles = ((0.1, 0.0, 0.1),)
        s._hitbox_circle = (0.1, 0.0, 0.1)
        s._hitbox_ellipses = ((0.0, 0.1, 0.08, 0.04, 0.0),)
        s._hitbox_ellipse = (0.0, 0.1, 0.08, 0.04, 0.0)
        s._snapshot_hitbox_base()
        s._hitbox_scale = (0.5, 1.0)
        s._apply_hitbox_shaping()
        self.assertEqual(len(s._hitbox_ellipses), 2,
                         f"B3 non-uniform: original ellipse lost, got {s._hitbox_ellipses}")

    def test_b4_empty_circle_falls_back_to_circle(self):
        path = self.tmp("empty.png")
        info = skia.ImageInfo.Make(32, 32, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().clear(skia.ColorTRANSPARENT)
        surf.makeImageSnapshot().save(path, skia.kPNG)
        s = self.track(Sprite(path, center=(0, 0), width=64, height=64, hitbox_shape="circle"))
        specs = s._collision_specs()
        self.assertEqual(specs[0][0], "circle", f"B4: empty circle fell back to {specs}")

    def test_b6_authored_boxes_preferred_on_locked_refit(self):
        p2 = self.tmp("strip.png")
        info = skia.ImageInfo.Make(64, 32, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().drawPaint(skia.Paint(Color=skia.ColorWHITE))
        surf.makeImageSnapshot().save(p2, skia.kPNG)
        sh = Sheet(p2, cols=2)
        sh._frame_at(0).boxes = ((0, 0, 10, 10),)
        sh._frame_at(1).boxes = ((5, 5, 10, 10),)
        s = self.track(Sprite(sh, frame=0, center=(0, 0), height=32,
                              hitbox_shape="auto", hitbox_source="each"))
        s._ensure_auto_baked()
        self.assertEqual(s._hitbox_locked_kind, "boxes")
        s.frame = 1
        s._ensure_auto_baked()
        from scena.atlas import boxes_to_local
        want = boxes_to_local(sh._frame_at(1).boxes, sh._frame_at(1))
        self.assertEqual(len(s._hitbox_boxes), 1)
        for got, exp in zip(s._hitbox_boxes[0], want[0]):
            self.assertAlmostEqual(got, exp, places=6,
                                   msg=f"B6: locked refit ignored authored, got {s._hitbox_boxes} want {want}")

    def test_b7_clip_still_key_stable(self):
        p = self.tmp("strip.png")
        info = skia.ImageInfo.Make(64, 32, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().drawPaint(skia.Paint(Color=skia.ColorWHITE))
        surf.makeImageSnapshot().save(p, skia.kPNG)
        sh = Sheet(p, cols=2)
        sh.clip("walk", [0, 1], fps=8)
        s = self.track(Sprite(sh, frame=0, center=(0, 0), size=32, hitbox_source="clip"))
        s._ensure_auto_baked()
        self.assertTrue(s._auto_baked)
        s.frame = 1
        self.assertTrue(s._auto_baked, "B7: still frame write redundantly invalidated clip bake")
        self.assertEqual(s._hitbox_baked_key, ("still", int(s._construct_frame)))

    def test_b9_anchor_offset_reject_nonfinite(self):
        path = self.tmp("sq.png")
        _write_rect_png(path, 32, 32)
        with self.assertRaises((ValueError, TypeError)):
            Sprite(path, center=(0, 0), size=32, hitbox_anchor=(float("nan"), 0.0))
        with self.assertRaises((ValueError, TypeError)):
            Sprite(path, center=(0, 0), size=32, hitbox_anchor=(0.0, float("inf")))
        with self.assertRaises((ValueError, TypeError)):
            Sprite(path, center=(0, 0), size=32, offset=(float("nan"), 0.0))
        with self.assertRaises((ValueError, TypeError)):
            Sprite(path, center=(0, 0), size=32, offset=(0.0, float("inf")))

    def test_b10_stale_hitbox_from_falls_back(self):
        p = self.tmp("strip.png")
        info = skia.ImageInfo.Make(64, 32, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().drawPaint(skia.Paint(Color=skia.ColorWHITE))
        surf.makeImageSnapshot().save(p, skia.kPNG)
        sh = Sheet(p, cols=2)
        sh.clip("walk", [0, 1], fps=8)
        s = self.track(Sprite(sh, center=(0, 0), size=32, hitbox_source="walk"))
        s._ensure_auto_baked()
        sh._cycles.pop("walk")
        s._invalidate_auto_bake()
        try:
            s._ensure_auto_baked()
        except (ValueError, IndexError) as e:
            self.fail(f"B10: stale hitbox_from raised instead of falling back: {e}")
        # snapshot path (used by collision.step) must not raise either
        try:
            snapshot_shape(s)
        except (ValueError, IndexError) as e:
            self.fail(f"B10: snapshot raised on stale spec: {e}")

    def test_b11_pin_uses_authored_boxes(self):
        path = self.tmp("padded.png")
        _write_padded_png(path, canvas_w=64, canvas_h=64, blob=(20, 8, 24, 40))
        sh = Sheet(path)
        sh._frame_at(0).boxes = ((20, 8, 24, 10),)
        s = self.track(Sprite(sh, center=(0, 0), width=64, height=64,
                              hitbox_shape="auto", hitbox_anchor="bottom"))
        s._ensure_auto_baked()
        from scena.atlas import boxes_to_local
        want = boxes_to_local(sh._frame_at(0).boxes, sh._frame_at(0))
        wmin = min(v[1] - abs(v[3]) * 0.5 for v in want)
        got = s._bake_reference_local_aabb()
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got[1], wmin, places=6,
                               msg=f"B11: pin {got} should sit on authored {want}")

    def test_b8_tilt_pivot_mirrors_with_flip(self):
        # Paint flips the cell first (innermost), then tilts: the pivot is the
        # anchor as drawn. Under flip it mirrors with the emitted collider.
        path = self.tmp("sq.png")
        _write_rect_png(path, 32, 32)
        s = self.track(Sprite(path, center=(0, 0), width=64, height=64,
                              hitbox_shape="rect", hitbox_anchor="left", offset=(6, 4)))
        s._ensure_auto_baked()
        p0 = s._tilt_pivot_local()
        s.flip_x = True
        self.assertEqual(s._tilt_pivot_local(), (-p0[0], p0[1]))
        s.flip_y = True
        self.assertEqual(s._tilt_pivot_local(), (-p0[0], -p0[1]))

    def test_tilt_pivot_is_collider_anchor_under_flip(self):
        # Regression: pivot stayed pre-flip, so a flipped sprite leaned about
        # a point inside its collider instead of the anchored edge.
        path = self.tmp("sq.png")
        _write_rect_png(path, 32, 32)
        for anchor in ("left", "right", "bottom", (0.5, -1.0)):
            for fx, fy in ((False, False), (True, False), (False, True), (True, True)):
                s = self.track(Sprite(
                    path, center=(0, 0), width=64, height=64, hitbox_shape="rect",
                    hitbox_anchor=anchor, offset=(6, 4), flip_x=fx, flip_y=fy,
                ))
                spec = s._collision_specs()[0]
                self.assertEqual(spec[0], "aabb")
                x0, y0, x1, y1 = spec[1:]
                # The collider anchor, mapped the same way the prim is.
                ax, ay = {"left": (-1, 0), "right": (1, 0), "bottom": (0, -1)}.get(
                    anchor, anchor) if isinstance(anchor, str) else anchor
                if fx:
                    ax = -ax
                if fy:
                    ay = -ay
                want = ((x0 + x1) * 0.5 + ax * (x1 - x0) * 0.5,
                        (y0 + y1) * 0.5 + ay * (y1 - y0) * 0.5)
                px, py = s._tilt_pivot_local()
                self.assertAlmostEqual(px, want[0], places=4, msg=(anchor, fx, fy))
                self.assertAlmostEqual(py, want[1], places=4, msg=(anchor, fx, fy))
                # Painted pivot is a fixed point of tilt.
                s.tilt = 25
                mx, my = s._map_silhouette_local(
                    (-px if fx else px), (py if fy else -py),
                    flip_x=-1.0 if fx else 1.0, flip_y=-1.0 if fy else 1.0,
                    draw_ang=0.0, tilt=25.0, px=px, py=py,
                )
                self.assertAlmostEqual(mx, px, places=4)
                self.assertAlmostEqual(my, py, places=4)
                s.destroy()

    def test_b12_tuple_order_stable(self):
        pa = self.tmp("a.png")
        pb = self.tmp("b.png")
        _write_rect_png(pa, 32, 32)
        _write_rect_png(pb, 64, 32)
        sh = Sheet([pa, pb])
        sh.clip("walk", [0], fps=8)
        sh.clip("run", [1], fps=8)
        a = self.track(Sprite(sh, center=(0, 0), height=48, hitbox_source=("walk", "run")))
        b = self.track(Sprite(sh, center=(0, 0), height=48, hitbox_source=("run", "walk")))
        self.assertEqual(a._collision_specs(), b._collision_specs())


class TestReviewedSpriteFixes(SpriteTestCase):
    def _png(self, name, w, h):
        path = self.tmp(name)
        _write_rect_png(path, w, h)
        return path

    def test_nonuniform_circle_scale_keeps_source_aspect(self):
        path = self._png("tall.png", 64, 128)
        s = self.track(Sprite(
            path, center=(0, 0), width=64, height=128, hitbox_shape="circle",
        ))
        s._hitbox_circles = ((0.0, 0.0, 25.0 / 64.0),)
        s._hitbox_circle = s._hitbox_circles[0]
        s._hitbox_ellipses = ()
        s._hitbox_ellipse = None
        s._hitbox_ref_src_w = 64.0
        s._hitbox_ref_src_h = 128.0
        s._commit_hitbox_base()
        s.hitbox.scale = (1.0, 1.01)
        radii = []
        for spec in s._collision_specs():
            if spec[0] == "ellipse":
                radii.append(spec[4])
            elif spec[0] == "circle":
                radii.append(spec[3])
        self.assertEqual(len(radii), 1)
        self.assertAlmostEqual(radii[0], 25.25, delta=1.0)
        self.assertLess(radii[0], 30.0)

    def test_proxy_circumradius_covers_emitted_ry(self):
        path = self._png("wide.png", 200, 100)
        s = self.track(Sprite(
            path, center=(0, 0), width=100, height=100, hitbox_shape="circle",
        ))
        s._hitbox_circles = ((0.0, 0.0, 0.5),)
        s._hitbox_circle = s._hitbox_circles[0]
        s._hitbox_ellipses = ()
        s._hitbox_ellipse = None
        s._hitbox_ref_src_w = 200.0
        s._hitbox_ref_src_h = 100.0
        s._auto_baked = True
        s._recompute_hitbox_local_radius()
        specs = [t for t in s._collision_specs() if t[0] in ("circle", "ellipse")]
        self.assertTrue(specs)
        ry = specs[0][3] if specs[0][0] == "circle" else specs[0][4]
        w, h = s._hitbox_pose_wh()
        reach = math.hypot(
            s._hitbox_extent_x * abs(w), s._hitbox_extent_y * abs(h),
        )
        self.assertGreaterEqual(reach + 1e-6, ry)

    def test_size_assignment_survives_play(self):
        wide = self._png("wide2.png", 80, 40)
        tall = self._png("tall2.png", 40, 80)
        sh = Sheet([wide, tall])
        sh.clip("wide", [0], fps=8)
        sh.clip("tall", [1], fps=8)
        s = self.track(Sprite(sh, center=(0, 0), size=60))
        s.play("wide")
        s.size = 90
        s.play("tall")
        self.assertAlmostEqual(max(abs(s.width), abs(s.height)), 90.0, delta=0.1)

    def test_clone_keeps_size_intent(self):
        path = self._png("sq.png", 32, 32)
        sized = self.track(Sprite(path, center=(0, 0), size=70))
        cloned = sized.clone()
        self._owned.append(cloned)
        self.assertEqual(cloned._size_intent, "size")
        self.assertAlmostEqual(cloned._size_intent_value, 70.0)
        tall = self.track(Sprite(path, center=(30, 0), height=40))
        cloned_h = tall.clone()
        self._owned.append(cloned_h)
        self.assertEqual(cloned_h._size_intent, "height")
        self.assertAlmostEqual(abs(cloned_h.height), abs(tall.height), delta=0.1)

    def test_svg_box_matches_sprite_box(self):
        from scena import Box
        path = self._png("icon.png", 20, 10)
        region = Box(center=(12, 24), width=80, height=40)
        sprite = self.track(Sprite(path, box=region))
        svg = self.track(Svg(
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"></svg>',
            box=region,
        ))
        self.assertAlmostEqual(float(svg.center.x), float(sprite.center.x), delta=0.5)
        self.assertAlmostEqual(float(svg.center.y), float(sprite.center.y), delta=0.5)
        self.assertAlmostEqual(abs(svg.width), abs(sprite.width), delta=1.0)
        self.assertAlmostEqual(abs(svg.height), abs(sprite.height), delta=1.0)

    def test_time_scale_does_not_jump_elapsed(self):
        import scena.sprite as sprite_mod
        path = self.tmp("clip.png")
        _write_grid_png(path, cell=8, cols=4, rows=1)
        sh = Sheet(path, cols=4, fps=8)
        s = self.track(Sprite(sh, center=(0, 0), size=32))
        held = {"t": 0.0}
        orig = sprite_mod._world_time
        sprite_mod._world_time = lambda: held["t"]
        try:
            s.play("default")
            held["t"] = 0.4
            before = s._play_elapsed()
            frame = s.frame
            s.time_scale = 4.0
            self.assertAlmostEqual(s._play_elapsed(), before, delta=1e-6)
            self.assertEqual(s.frame, frame)
            s.time_scale = 0.0
            held["t"] = 5.0
            self.assertAlmostEqual(s._play_elapsed(), before, delta=1e-6)
        finally:
            sprite_mod._world_time = orig

    def test_mixed_circle_and_ellipse_both_emit(self):
        path = self._png("mix.png", 64, 64)
        s = self.track(Sprite(path, center=(0, 0), size=64, hitbox_shape="rect"))
        s._hitbox_circles = ((0.0, 0.0, 0.2),)
        s._hitbox_circle = None
        s._hitbox_ellipses = ((0.25, 0.0, 0.15, 0.4, 0.3),)
        s._hitbox_ellipse = None
        s._hitbox_boxes = ()
        s._hitbox_ref_src_w = 64.0
        s._hitbox_ref_src_h = 64.0
        s._auto_baked = True
        kinds = [spec[0] for spec in s._collision_specs()]
        self.assertIn("circle", kinds)
        self.assertIn("ellipse", kinds)


def _write_half_strip(path):
    """Two 32×32 cells. Cell 0 is opaque on its left half; cell 1 on its right."""
    info = skia.ImageInfo.Make(64, 32, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    paint = skia.Paint(Color=skia.ColorWHITE, AntiAlias=False)
    c.drawRect(skia.Rect.MakeXYWH(0, 0, 16, 32), paint)
    c.drawRect(skia.Rect.MakeXYWH(48, 0, 16, 32), paint)
    surf.makeImageSnapshot().save(path, skia.kPNG)


def _write_clear_png(path, side=32):
    info = skia.ImageInfo.Make(side, side, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    surf.getCanvas().clear(skia.ColorTRANSPARENT)
    surf.makeImageSnapshot().save(path, skia.kPNG)


class TestSpritePointerAlpha(SpriteTestCase):
    """Pointer samples the current cell. Collision keeps the baked hitbox."""

    def _strip(self):
        path = self.tmp("halves.png")
        _write_half_strip(path)
        return self.track(Sprite(
            Sheet(path, cols=2), center=(0, 0), size=32, frame=0,
        ))

    def test_opaque_pixel_hits_and_padding_misses(self):
        s = self._strip()
        self.assertTrue(s.contains_point(-8, 0))
        self.assertFalse(s.contains_point(8, 0))
        self.assertFalse(s.contains_point(20, 0))

    def test_frame_switch_moves_the_blob(self):
        s = self._strip()
        s.frame = 1
        self.assertFalse(s.contains_point(-8, 0))
        self.assertTrue(s.contains_point(8, 0))

    def test_flip_x_mirrors_the_blob(self):
        s = self._strip()
        s.flip_x = True
        self.assertFalse(s.contains_point(-8, 0))
        self.assertTrue(s.contains_point(8, 0))

    def test_art_angle_samples_the_painted_pixels(self):
        s = self._strip()
        s.art_angle = 90
        s.angle = 0
        self.assertAlmostEqual(s._draw_angle(), -90.0)
        self.assertTrue(s.contains_point(0, 8))
        self.assertFalse(s.contains_point(-8, 0))

    def test_tilt_samples_the_painted_pixels(self):
        s = self._strip()
        s.tilt = 90
        self.assertTrue(s.contains_point(0, -8))
        self.assertFalse(s.contains_point(-8, 0))

    def test_clear_cell_misses(self):
        path = self.tmp("clear.png")
        _write_clear_png(path)
        s = self.track(Sprite(path, center=(0, 0), size=32))
        self.assertFalse(s.contains_point(0, 0))
        self.assertFalse(s.contains_point(10, 0))

    def test_glow_does_not_grow_the_hit(self):
        s = self._strip()
        s.glow = CheapGlow(color="tomato", radius=12)
        self.assertTrue(s.contains_point(-8, 0))
        self.assertFalse(s.contains_point(8, 0))

    def test_skinny_hitbox_is_not_the_pointer(self):
        path = self.tmp("solid.png")
        _write_rect_png(path, 32, 32)
        s = self.track(Sprite(
            path, center=(0, 0), size=64, hitbox_shape="rect",
            hitbox_scale=(0.5, 1.0), group="solid",
        ))
        s.collidable = True
        self.assertTrue(s.contains_point(24, 0))
        hits = get_collision_system().query_point(24, 0)
        self.assertNotIn(s, hits)
        self.assertIn(s, get_collision_system().query_point(0, 0))



class TestClipClockUnderPark(unittest.TestCase):
    """PB-note (graphics review): the clip clock is world time, not a timer.
    A parked sprite's clip keeps advancing; ``time_scale = 0`` holds it."""

    def test_park_advances_the_clip_and_time_scale_zero_holds_it(self):
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from system_support import SystemWorld
        w = SystemWorld(draw=False)
        try:
            d = tempfile.mkdtemp()
            path = os.path.join(d, "g.png")
            _write_grid_png(path, cell=16, cols=2, rows=1)
            sheet = Sheet(path, cell=(16, 16))
            sheet.clip("a", [0, 1], fps=4)
            held = Sprite(sheet, center=(0, 0), height=16)
            parked = Sprite(sheet, center=(0, 0), height=16)
            held.play("a")
            parked.play("a")
            held.time_scale = 0
            held.active = False
            parked.active = False
            w.step(45)                      # 0.75 s at 4 fps: cell 1
            held.active = True
            held.time_scale = 1
            parked.active = True
            self.assertEqual(held.frame, 0)
            self.assertEqual(parked.frame, 1)
        finally:
            w.teardown()


if __name__ == "__main__":
    unittest.main()

