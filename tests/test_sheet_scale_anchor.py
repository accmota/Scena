"""One scale per sprite, ``Sheet(anchor=)``, and ``clip(offset=)``.

Every cell draws at its PNG (atlas ``sourceSize``) size times one design-units
per pixel scale, fixed by the size asked at construction. ``anchor=`` is the
default pivot of cells without an authored atlas pivot; ``sprite.center`` sits
on it. ``offset=`` nudges one clip's art in art pixels (y-up). Headless.

    python -m unittest tests.test_sheet_scale_anchor -v
"""
import json
import math
import unittest

from scena import STATIC, Rect, Sheet, Sprite, clock, resolve
from scena.collision import _collision_pose_xy, get_collision_system, snapshot_shape
from scena.process import tick_processes
from tests.test_hitbox_parts import _spec_bounds
from tests.test_sprite import SpriteTestCase, _frame, _write_rect_png


class SheetScaleTestCase(SpriteTestCase):
    """Three clips with different canvases, like a pack cropped per animation.

    idle 20×40, slide 30×32, dead 40×44 (px). ``height=80`` on idle → 2 du/px.
    """

    def ninja(self, **sheet_kwargs):
        files = []
        for name, w, h in (("idle", 20, 40), ("slide", 30, 32), ("dead", 40, 44)):
            path = self.tmp(f"{name}.png")
            _write_rect_png(path, w, h)
            files.append(path)
        sheet = Sheet(files, **sheet_kwargs)
        sheet.clip("idle", [0], fps=4)
        sheet.clip("slide", [1], fps=4)
        return sheet

    def hero(self, sheet, **kwargs):
        kwargs.setdefault("height", 80)
        kwargs.setdefault("center", (0, 0))
        return self.track(Sprite(sheet, frame=0, **kwargs))

    def visual_box(self, s):
        cx, cy, w, h, _ang = s._oriented_frame()
        return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


class TestOneScalePerSprite(SheetScaleTestCase):
    def test_each_clip_draws_at_its_png_size(self):
        s = self.hero(self.ninja())
        self.assertAlmostEqual(float(s.height), 80.0)
        self.assertAlmostEqual(float(s.width), 40.0)
        s.play("slide")
        self.assertAlmostEqual(float(s.height), 64.0)
        self.assertAlmostEqual(float(s.width), 60.0)
        s.frame = 2
        self.assertAlmostEqual(float(s.height), 88.0)
        self.assertAlmostEqual(float(s.width), 80.0)
        s.play("idle")
        self.assertAlmostEqual(float(s.height), 80.0)
        self.assertAlmostEqual(float(s.width), 40.0)

    def test_blit_scale_is_the_same_for_every_cell(self):
        s = self.hero(self.ninja())
        k0 = s._pixel_scale()
        s.play("slide")
        self.assertEqual(s._pixel_scale(), k0)
        self.assertEqual(s._pixel_scale(s._sheet._frame_at(2)), k0)

    def test_size_write_rescales_every_clip(self):
        s = self.hero(self.ninja())
        s.size = 40                           # idle box 40×80 → 20×40: 1 du/px
        s.play("slide")
        self.assertAlmostEqual(float(s.height), 32.0)
        self.assertAlmostEqual(float(s.width), 30.0)

    def test_stretch_keeps_per_axis_scale(self):
        s = self.hero(self.ninja(), width=40, height=40)   # kx=2, ky=1
        s.play("slide")
        self.assertAlmostEqual(float(s.width), 60.0)
        self.assertAlmostEqual(float(s.height), 32.0)

    def test_clone_keeps_the_scale(self):
        s = self.hero(self.ninja())
        s.play("slide")
        c = self.track(s.clone())
        self.assertAlmostEqual(float(c.height), float(s.height))
        c.play("idle")
        self.assertAlmostEqual(float(c.height), 80.0)


class TestSheetAnchor(SheetScaleTestCase):
    def test_default_anchor_is_center(self):
        s = self.hero(self.ninja())
        s.play("slide")
        cx, cy, _w, _h, _a = s._oriented_frame()
        self.assertAlmostEqual(cx, 0.0)
        self.assertAlmostEqual(cy, 0.0)

    def test_bottom_anchor_keeps_every_clip_on_the_center_line(self):
        s = self.hero(self.ninja(anchor="bottom"))
        for clip in ("idle", "slide"):
            s.play(clip)
            _x0, y0, _x1, y1 = self.visual_box(s)
            self.assertAlmostEqual(y0, 0.0, msg=clip)
            self.assertAlmostEqual(y1, float(s.height), msg=clip)
        s.frame = 2
        _x0, y0, _x1, _y1 = self.visual_box(s)
        self.assertAlmostEqual(y0, 0.0)

    def test_numeric_anchor_pair(self):
        s = self.hero(self.ninja(anchor=(0, -0.5)))    # halfway down
        _cx, cy, _w, h, _a = s._oriented_frame()
        self.assertAlmostEqual(cy, h / 4)

    def test_invalid_anchor_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.ninja(anchor="feet")
        self.assertIn("anchor", str(ctx.exception))
        with self.assertRaises(TypeError):
            self.ninja(anchor=3)

    def test_flip_mirrors_about_the_anchor(self):
        s = self.hero(self.ninja(anchor="left"))
        x0, _y0, _x1, _y1 = self.visual_box(s)
        self.assertAlmostEqual(x0, 0.0)
        s.flip_x = True
        _x0, _y0, x1, _y1 = self.visual_box(s)
        self.assertAlmostEqual(x1, 0.0)

    def _atlas(self, frames):
        png = self.tmp("atlas.png")
        _write_rect_png(png, 32, 16)
        path = self.tmp("atlas.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"meta": {"image": "atlas.png"}, "frames": frames}, f)
        return png, path

    def test_authored_atlas_pivot_beats_the_anchor(self):
        png, path = self._atlas({
            "a": {"frame": {"x": 0, "y": 0, "w": 16, "h": 16}, "pivot": {"x": 0.0, "y": 0.5}},
            "b": {"frame": {"x": 16, "y": 0, "w": 16, "h": 16}},
        })
        sheet = Sheet(png, atlas=path, anchor="bottom")
        s = self.track(Sprite(sheet, frame="a", center=(0, 0), size=16))
        cx, cy, _w, _h, _a = s._oriented_frame()
        self.assertAlmostEqual(cx, 8.0)                 # authored: left edge
        self.assertAlmostEqual(cy, 0.0)
        s.frame = "b"                                   # no pivot → anchor
        cx, cy, _w, _h, _a = s._oriented_frame()
        self.assertAlmostEqual(cx, 0.0)
        self.assertAlmostEqual(cy, 8.0)

    def test_center_anchor_returns_the_shared_frames(self):
        sheet = self.ninja()
        self.assertIs(sheet._frame_at(1), sheet._atlas_frames[1])


class TestClipOffset(SheetScaleTestCase):
    def test_offset_moves_the_art_in_art_pixels(self):
        sheet = self.ninja()
        sheet.clip("dead", [2], fps=4, offset=(4, 3))  # right 4 px, up 3 px
        s = self.hero(sheet)
        s.play("dead")
        cx, cy, _w, _h, _a = s._oriented_frame()
        self.assertAlmostEqual(cx, 8.0)                 # 4 px × 2 du/px
        self.assertAlmostEqual(cy, 6.0)

    def test_offset_mirrors_under_flip(self):
        sheet = self.ninja()
        sheet.clip("dead", [2], fps=4, offset=(4, 0))
        s = self.hero(sheet)
        s.play("dead")
        s.flip_x = True
        cx, _cy, _w, _h, _a = s._oriented_frame()
        self.assertAlmostEqual(cx, -8.0)

    def test_offset_on_top_of_the_anchor(self):
        sheet = self.ninja(anchor="bottom")
        sheet.clip("dead", [2], fps=4, offset=(0, 5))
        s = self.hero(sheet)
        s.play("dead")
        _x0, y0, _x1, _y1 = self.visual_box(s)
        self.assertAlmostEqual(y0, 10.0)

    def test_strip_takes_offset(self):
        sheet = self.ninja()
        path = self.tmp("jump.png")
        _write_rect_png(path, 40, 20)                   # two 20×20 cells
        sheet.strip("jump", path, cols=2, fps=4, offset=(0, -2))
        s = self.hero(sheet)
        s.play("jump")
        _cx, cy, _w, _h, _a = s._oriented_frame()
        self.assertAlmostEqual(cy, -4.0)

    def test_conflicting_offsets_for_one_frame_raise(self):
        sheet = self.ninja()
        sheet.clip("dead", [2], fps=4, offset=(4, 0))
        sheet.clip("dead_again", [2], fps=4, offset=(4, 0))   # same: fine
        with self.assertRaises(ValueError) as ctx:
            sheet.clip("dead_moved", [2], fps=4, offset=(1, 0))
        self.assertIn("offset", str(ctx.exception))

    def test_bad_offset_raises(self):
        sheet = self.ninja()
        with self.assertRaises(TypeError):
            sheet.clip("dead", [2], fps=4, offset=5)
        with self.assertRaises(ValueError):
            sheet.clip("dead", [2], fps=4, offset=(math.inf, 0))


class TestHitboxWithOneScale(SheetScaleTestCase):
    def test_body_collider_does_not_change_across_clips(self):
        """The walker body must not grow, shrink or sink when a clip plays.

        Regression: ``_hitbox_pose_wh`` used the current clip's box, so a
        taller dead cell rescaled a body baked from the standing clip.
        """
        for anchor in ("center", "bottom"):
            s = self.hero(
                self.ninja(anchor=anchor), hitbox_shape="rect",
                hitbox_source=("idle",), hitbox_anchor="bottom",
            )
            body = s._collision_specs()
            for step in ("slide", 2, "idle"):
                if isinstance(step, int):
                    s.frame = step
                else:
                    s.play(step)
                self.assertEqual(s._collision_specs(), body, msg=(anchor, step))

    def test_union_of_clips_is_aligned_on_the_anchor(self):
        s = self.hero(
            self.ninja(anchor="bottom"), hitbox_shape="rect",
            hitbox_source=("idle", "slide"),
        )
        minx, miny, maxx, maxy = snapshot_shape(s)[0].aabb
        self.assertAlmostEqual(miny, 0.0, places=3)     # feet line shared
        self.assertAlmostEqual(maxy, 80.0, places=3)    # taller clip (idle)
        self.assertAlmostEqual(maxx - minx, 60.0, places=3)   # wider clip (slide)

    def test_each_part_follows_the_scaled_cell(self):
        s = self.hero(self.ninja(anchor="bottom"), hitbox_shape="rect", hitbox_source=("idle",))
        hb = s.add_hitbox(group="dor", shape="rect")
        s.play("idle")
        _frame(0.01)
        _x0, y0, _x1, y1 = _spec_bounds(hb._collision_specs())
        self.assertAlmostEqual(y1 - y0, 80.0, places=3)
        s.play("slide")
        _frame(0.01)
        _x0, y0, _x1, y1 = _spec_bounds(hb._collision_specs())
        self.assertAlmostEqual(y0, 0.0, places=3)
        self.assertAlmostEqual(y1 - y0, 64.0, places=3)   # ducks



class TestConstructCell(SheetScaleTestCase):
    """Without ``frame=``, a Sprite starts on its sheet's first clip.

    ``height=`` fixes the sprite's one scale on the construct cell, so that
    cell must be the art the author means — not cell 0 of a packed atlas.
    """

    def _catalog(self):
        """Packed atlas: cell 0 is a small unrelated 'beam', then two enemies."""
        png = self.tmp("space.png")
        _write_rect_png(png, 48, 16)
        path = self.tmp("space.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"meta": {"image": "space.png"}, "frames": {
                "beam": {"frame": {"x": 0, "y": 0, "w": 8, "h": 4}},
                "green": {"frame": {"x": 16, "y": 0, "w": 16, "h": 16}},
                "red": {"frame": {"x": 32, "y": 0, "w": 16, "h": 16}},
            }}, f)
        return Sheet(png, atlas=path)

    def test_no_frame_starts_on_the_first_clip(self):
        sheet = self._catalog()
        sheet.clip("green", ["green"], fps=1)
        sheet.clip("red", ["red"], fps=1)
        s = self.track(Sprite(sheet, height=40, center=(0, 0)))
        self.assertEqual(s._current_cell().name, "green")
        self.assertAlmostEqual(float(s.height), 40.0)
        s.play("red")                                  # Galaga wasp path
        self.assertAlmostEqual(float(s.height), 40.0)

    def test_explicit_frame_wins(self):
        sheet = self._catalog()
        sheet.clip("green", ["green"], fps=1)
        s = self.track(Sprite(sheet, frame="beam", height=4, center=(0, 0)))
        self.assertEqual(s._current_cell().name, "beam")
        s.play("green")
        self.assertAlmostEqual(float(s.height), 16.0)  # true size at 1 du/px

    def test_no_clips_starts_on_cell_zero(self):
        s = self.track(Sprite(self._catalog(), height=4, center=(0, 0)))
        self.assertEqual(s._current_cell().name, "beam")


class TestPixelSize(SheetScaleTestCase):
    """``Sheet(pixel_size=)``: every PNG pixel is ``pixel_size`` design units.

    Sprites of the sheet that pass no size keyword draw at their PNG size ×
    ``pixel_size``; an explicit ``height=`` / ``size=`` / ``box=`` still wins.
    """

    def test_no_size_keyword_uses_the_pixel_size(self):
        s = self.track(Sprite(self.ninja(pixel_size=2), frame=0, center=(0, 0)))
        self.assertAlmostEqual(float(s.height), 80.0)          # 40 px × 2
        self.assertAlmostEqual(float(s.width), 40.0)
        s.play("slide")
        self.assertAlmostEqual(float(s.height), 64.0)          # 32 px × 2

    def test_sprites_of_one_sheet_keep_their_relative_size(self):
        sheet = self.ninja(pixel_size=1.5)
        idle = self.track(Sprite(sheet, frame=0, center=(0, 0)))
        dead = self.track(Sprite(sheet, frame=2, center=(100, 0)))
        self.assertAlmostEqual(float(idle.height), 60.0)        # 40 × 1.5
        self.assertAlmostEqual(float(dead.height), 66.0)        # 44 × 1.5

    def test_fraction_shrinks_a_big_png(self):
        s = self.track(Sprite(self.ninja(pixel_size=0.5), frame=0, center=(0, 0)))
        self.assertAlmostEqual(float(s.height), 20.0)

    def test_explicit_size_wins(self):
        sheet = self.ninja(pixel_size=2)
        a = self.track(Sprite(sheet, frame=0, height=10, center=(0, 0)))
        self.assertAlmostEqual(float(a.height), 10.0)
        a.play("slide")
        self.assertAlmostEqual(float(a.height), 8.0)            # that sprite's own scale
        b = self.track(Sprite(sheet, frame=0, size=20, center=(0, 0)))
        self.assertAlmostEqual(float(b.height), 20.0)

    def test_box_wins(self):
        from scena import Box
        s = self.track(Sprite(
            self.ninja(pixel_size=2), frame=0,
            box=Box(center=(0, 0), width=30, height=30),
        ))
        self.assertAlmostEqual(float(s.height), 30.0)           # fits the box, not 80

    def test_scale_multiplies_on_top(self):
        s = self.track(Sprite(self.ninja(pixel_size=2), frame=0, center=(0, 0)))
        s.scale = 1.5
        _cx, _cy, _w, h, _a = s._oriented_frame()
        self.assertAlmostEqual(h, 120.0)

    def test_clone_keeps_the_size(self):
        s = self.track(Sprite(self.ninja(pixel_size=2), frame=0, center=(0, 0)))
        s.play("slide")
        c = self.track(s.clone())
        self.assertAlmostEqual(float(c.height), 64.0)
        c.play("idle")
        self.assertAlmostEqual(float(c.height), 80.0)

    def test_trimmed_atlas_uses_the_untrimmed_source_size(self):
        png = self.tmp("trim.png")
        _write_rect_png(png, 16, 16)
        path = self.tmp("trim.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"meta": {"image": "trim.png"}, "frames": {"a": {
                "frame": {"x": 0, "y": 0, "w": 16, "h": 16},
                "spriteSourceSize": {"x": 4, "y": 8, "w": 16, "h": 16},
                "sourceSize": {"w": 24, "h": 32},
            }}}, f)
        s = self.track(Sprite(Sheet(png, atlas=path, pixel_size=2), center=(0, 0)))
        self.assertAlmostEqual(float(s.height), 64.0)           # 32 px canvas × 2
        self.assertAlmostEqual(float(s.width), 48.0)

    def test_without_pixel_size_the_default_size_is_unchanged(self):
        sheet = self.ninja()
        self.assertIsNone(sheet.pixel_size)
        s = self.track(Sprite(sheet, frame=0, center=(0, 0)))
        self.assertGreaterEqual(float(s.height), 48.0)          # default longer side

    def test_is_read_only_and_validated(self):
        sheet = self.ninja(pixel_size=3)
        self.assertEqual(sheet.pixel_size, 3.0)
        with self.assertRaises(AttributeError):
            sheet.pixel_size = 2
        for bad in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError, msg=bad):
                self.ninja(pixel_size=bad)
        for bad in (True, "3", (3, 3)):
            with self.assertRaises(TypeError, msg=bad):
                self.ninja(pixel_size=bad)


class TestRestingBodyAcrossClips(SheetScaleTestCase):
    """A walker resting under ``resolve()`` must not float or sink on a clip change.

    Regression: the snapshot cache keyed sprites on the *drawn* box centre
    (``Graphic._center_xy`` → ``_oriented_frame``). A cell of another size or
    pivot moves that centre while the body does not, and the translate fast
    path slid the cached body prims by the visual shift — the ninja floated
    7 du while sliding and sank 5 du when dead. The key is now ``center``.
    """

    def rest_heights(self, sheet, clips):
        floor = self.track(Rect(center=(0, 40), width=400, height=40, group="chao"))
        floor.mass = STATIC
        s = self.hero(
            sheet, center=(0, 120), group="heroi", hitbox_shape="rect",
            hitbox_source=("idle",), hitbox_anchor="bottom",
        )
        s.mass = 1.0
        resolve("heroi", "chao", bounce=0.0)
        system = get_collision_system()
        vy, dt, out = 0.0, 1.0 / 60.0, []
        for clip in clips:
            for _ in range(40):
                vy -= 900.0 * dt
                if isinstance(clip, int):
                    s.frame = clip
                else:
                    s.play(clip)
                s.move_by(0, vy * dt)
                clock.advance(dt)
                tick_processes()
                system.step()
                if "bottom" in s.touching_sides:
                    vy = 0.0
            out.append(round(float(s.center.y), 3))
        return out

    def test_bottom_anchor_rests_on_one_line(self):
        heights = self.rest_heights(self.ninja(anchor="bottom"), ["idle", "slide", 2, "idle"])
        self.assertEqual(len(set(heights)), 1, heights)

    def test_centre_anchor_with_offset_rests_on_one_line(self):
        sheet = self.ninja()
        sheet.clip("dead", [2], fps=4, offset=(6, -3))
        heights = self.rest_heights(sheet, ["idle", "slide", "dead", "idle"])
        self.assertEqual(len(set(heights)), 1, heights)

    def test_cache_anchor_is_center_not_the_drawn_box(self):
        s = self.hero(self.ninja(anchor="bottom"))
        s.play("slide")
        self.assertEqual(_collision_pose_xy(s), (0.0, 0.0))
        cx, cy, _w, _h, _a = s._oriented_frame()
        self.assertNotEqual(cy, 0.0)                    # the drawn box did move


if __name__ == "__main__":
    unittest.main()
