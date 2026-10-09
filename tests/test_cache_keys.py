"""A cache hit equals a cold bake: every bake cache is keyed on all its inputs.

Graphics review R5 (2026-10-08):

* PA2: the atlas auto-hitbox key lacked the trim offset (``src_x`` /
  ``src_y``), so aliased atlas frames shared one hitbox shifted by the trim
  difference.
* PB10 / PB11: sprite-side caches were keyed on less than they read.

The oracle needs no model of any bake. Bake frame A to warm the cache, then
bake frame B (A with one ``AtlasFrame`` field changed), then clear the caches
and bake B cold. If the warm answer for B differs from the cold one, the key
misses that field. Fields that do not change the output pass on their own.

A coverage test pins the list of module caches: a new ``_*_CACHE`` in
``atlas.py`` / ``sprite.py`` must be added here with a bake to probe, or with
the reason it needs none. Known violations are shrink-only
(``graphics_known.CACHE_KEYS``).

    python tests/run_tiers.py focused test_cache_keys
"""
from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import skia  # noqa: E402

import scena.atlas as atlas  # noqa: E402
import scena.sprite as sprite_mod  # noqa: E402
from scena.atlas import AtlasFrame  # noqa: E402

# Bakes behind each module cache: (image, frame) -> result.
BAKES = {
    "_AUTO_CACHE": lambda img, fr: atlas.auto_collider_for_frame(img, fr),
    "_MASK_CACHE": lambda img, fr: atlas._display_mask(img, fr),
    "_FRAME_FX_CACHE": lambda img, fr: atlas.frame_fx_for_frame(img, fr),
    "_UNION_CACHE": lambda img, fr: atlas.auto_collider_for_frames(
        [(img, fr), (img, AtlasFrame("u", 32, 0, 16, 16))]),
}
# Caches with no frame bake behind them, and why.
NOT_BAKES = {
    "_ATLAS_CACHE": "path -> (mtime_ns, size) and the parsed atlas file; a rewritten file is parsed again",
    "_IMAGE_CACHE": "path -> decoded image (same)",
    "_PLACEHOLDER_CACHE": "label -> generated placeholder art (pure function of its key)",
    "_PACK_CACHE": "decoded images + names -> the strip packed from them (pure function of its key)",
}

# One changed value per AtlasFrame field (``name`` is a label, never baked).
VARIANTS = {
    "x": 4, "y": 4, "w": -4, "h": -4,
    "src_x": 3, "src_y": 5, "src_w": 6, "src_h": 6,
    "pivot_x": "0.2", "pivot_y": "0.8", "rotated": "toggle", "pivot_authored": "toggle",
    "boxes": "keep",
}


def _art() -> skia.Image:
    """64 x 32 sheet: an L shape at x 0..16 and a bar at x 32..48 (asymmetric)."""
    surf = skia.Surface(64, 32)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    p = skia.Paint(Color=skia.ColorBLACK)
    c.drawRect(skia.Rect.MakeXYWH(1, 1, 5, 14), p)
    c.drawRect(skia.Rect.MakeXYWH(1, 10, 13, 5), p)
    c.drawRect(skia.Rect.MakeXYWH(34, 3, 12, 6), p)
    return surf.makeImageSnapshot().makeRasterImage()


def _base() -> AtlasFrame:
    return AtlasFrame("a", 0, 0, 16, 16, src_x=0, src_y=0, src_w=16, src_h=16)


def _changed(field: str) -> AtlasFrame:
    fr = _base()
    v = VARIANTS[field]
    cur = getattr(fr, field)
    if v == "toggle":
        setattr(fr, field, not cur)
    elif isinstance(v, str) and v != "keep":
        setattr(fr, field, float(v))
    elif isinstance(v, int):
        setattr(fr, field, cur + v)
    return fr


def _norm(v, depth=0):
    if isinstance(v, np.ndarray):
        return ("array", v.shape, v.tobytes())
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (tuple, list)) and depth < 4:
        return tuple(_norm(x, depth + 1) for x in v)
    if isinstance(v, (int, str, bool)) or v is None:
        return v
    slots = getattr(type(v), "__slots__", None)
    if slots and depth < 4:
        return (type(v).__name__,) + tuple((s, _norm(getattr(v, s, None), depth + 1)) for s in slots
                                           if not s.startswith("local"))
    if isinstance(v, skia.Path):
        b = v.getBounds()
        return ("path", round(b.left(), 4), round(b.top(), 4), round(b.right(), 4), round(b.bottom(), 4))
    return type(v).__name__


def key_violations() -> dict:
    out = {}
    img = _art()
    for cache, bake in BAKES.items():
        for field in VARIANTS:
            atlas.reset_atlas_caches()
            bake(img, _base())                    # warm the cache with A
            warm = _norm(bake(img, _changed(field)))
            atlas.reset_atlas_caches()
            cold = _norm(bake(img, _changed(field)))
            if warm != cold:
                out[f"{cache} | {field}"] = "a warm hit differs from a cold bake"
    atlas.reset_atlas_caches()
    return out


def module_caches() -> set:
    names = set()
    for mod in (atlas, sprite_mod):
        for name, value in vars(mod).items():
            if re.fullmatch(r"_[A-Z_]*CACHE", name) and isinstance(value, dict):
                names.add(name)
    return names


class TestCacheKeysCoverTheirInputs(unittest.TestCase):
    def test_a_warm_hit_equals_a_cold_bake(self):
        from graphics_known import shrink_only
        shrink_only(self, key_violations(), "CACHE_KEYS")

    def test_canary_a_cache_that_ignores_its_key(self):
        from diff_support import assert_catches
        assert_catches(self, "test_cache_keys.TestCacheKeysCoverTheirInputs.test_a_warm_hit_equals_a_cold_bake",
                       [("scena.atlas", "_cache_get", lambda cache, key: next(iter(cache.values()), None))],
                       "a cache lookup that ignores the key")

    def test_a_big_sheet_bakes_each_frame_once(self):
        """PA1: one global cap of 128 under a ~200-cell sheet re-fitted every
        frame advance (13–40 ms each). A live sheet's bakes stay."""
        import tempfile
        from unittest import mock
        from scena.sprite import Sheet
        from tests.test_sprite import _write_grid_png
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "big.png")
            _write_grid_png(path, cell=8, cols=20, rows=10)
            atlas.reset_atlas_caches()
            sheet = Sheet(path, cell=(8, 8))
            frames = [sheet._frame_at(i) for i in range(sheet.nframes)]
            image = sheet._image
            fits = []
            real = atlas._choose_auto_collider
            with mock.patch.object(atlas, "_choose_auto_collider",
                                   lambda *a, **k: fits.append(1) or real(*a, **k)):
                for fr in frames:
                    atlas.auto_collider_for_frame(image, fr)
                first = len(fits)
                for fr in frames:
                    atlas.auto_collider_for_frame(image, fr)
            self.assertEqual(first, len(frames))
            self.assertEqual(len(fits), first, "a second pass re-fitted frames")
            atlas.reset_atlas_caches()

    def test_a_released_sheet_drops_its_union_bakes(self):
        """PA12: ``_UNION_CACHE`` was never purged with its sheet."""
        img = _art()
        atlas.reset_atlas_caches()
        atlas.bind_sheet_images(7, [img])
        BAKES["_UNION_CACHE"](img, _base())
        self.assertTrue(atlas._UNION_CACHE)
        atlas.release_sheet_token(7)
        self.assertEqual(len(atlas._UNION_CACHE), 0)
        atlas.reset_atlas_caches()

    def _sheet_sprite(self, tmp):
        from scena import Sprite
        from scena.sprite import Sheet
        from tests.test_sprite import _write_grid_png
        path = os.path.join(tmp, "s.png")
        _write_grid_png(path, cell=16, cols=2, rows=2)
        sheet = Sheet(path, cell=(16, 16))
        return sheet, Sprite(sheet, center=(80, 60), height=32)

    def test_shield_envelope_follows_a_stretch(self):
        """PB10: keyed on the size intent, the envelope went stale after ``width *= 2``."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _sheet, s = self._sheet_sprite(tmp)
            s._ensure_shield_envelope()
            s.width = float(s.width) * 2
            warm = s._ensure_shield_envelope()
            s._shield_env = None
            self.assertEqual(warm, s._ensure_shield_envelope())
            s.destroy()

    def test_blit_follows_a_later_clip_offset(self):
        """PB11: the source-rect cache was keyed on the frame index only, so a
        later ``clip(offset=)`` moved the pivot for hit tests but not the blit."""
        import tempfile
        from scena import Sprite
        from test_diff_draw import render
        with tempfile.TemporaryDirectory() as tmp:
            sheet, s = self._sheet_sprite(tmp)
            render([s])                                   # fills the cache for cell 0
            sheet.clip("shift", [0], fps=1, offset=(6, 0))
            fresh = Sprite(sheet, center=(80, 60), height=32)
            self.assertEqual(render([s]).tobytes(), render([fresh]).tobytes())
            s.destroy()
            fresh.destroy()

    def test_every_module_cache_is_listed(self):
        missing = sorted(module_caches() - set(BAKES) - set(NOT_BAKES))
        stale = sorted((set(BAKES) | set(NOT_BAKES)) - module_caches())
        self.assertEqual(missing, [], "a new cache: add its bake to BAKES, or a reason to NOT_BAKES")
        self.assertEqual(stale, [], "listed caches that no longer exist")

    def test_every_frame_field_is_varied(self):
        # ``_frozen`` is a write lock on cached frames, not a bake input.
        self.assertEqual(set(AtlasFrame.__slots__) - {"name", "_frozen"}, set(VARIANTS),
                         "a new AtlasFrame field: give it a VARIANTS entry")


if __name__ == "__main__":
    unittest.main(verbosity=2)
