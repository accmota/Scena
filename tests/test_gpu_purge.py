"""The run loop frees GPU resources unused for a second, twice a second.

Rule under test (Canvas Design.md, "GPU memory"): after each present,
``ScenaFramework._purge_idle_gpu`` calls Skia's
``purgeResourcesNotUsedInMs(GPU_PURGE_IDLE_S)`` at most once per
``GPU_PURGE_EVERY_S`` of wall time. Neon on moving shapes filled Skia's GPU
cache with one-use blur masks (~1.3 GB of process memory); textures drawn in
the last second are never purged. No context (headless) or a failing call
does nothing.

Loaded images are exempt (``style.gpu_image``): a decoded file draws, on a
GPU canvas, from a texture copy made once per image and context and held, so
no purge frees it; a raster canvas draws the raster. Measured on a real GL
context (not in the suite: a window per test process): the copy is
pixel-identical, and a 4096² image draws in 2–3 ms after a purge, against
9–12 ms for the raster, which uploads again.

Bug class guarded: a purge that runs every frame (cost), never (memory), or
with the wrong unit (the binding takes a ``timedelta``); a background shown
again after a pause uploaded again (the purge freed it).
"""
import datetime
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena  # noqa: F401
from scena.orchestration import GPU_PURGE_EVERY_S, GPU_PURGE_IDLE_S, ScenaFramework

O = sys.modules["scena.orchestration"]


class FakeContext:
    def __init__(self):
        self.calls = []

    def purgeResourcesNotUsedInMs(self, idle):
        if not isinstance(idle, datetime.timedelta):
            raise TypeError("the binding takes a timedelta")
        self.calls.append(idle)


class TestPurgeCadence(unittest.TestCase):
    def fw(self, ctx):
        fw = ScenaFramework.get_instance()
        patch = mock.patch.object(fw, "_context", ctx)
        patch.start()
        self.addCleanup(patch.stop)
        fw._gpu_purge_t = 0.0
        return fw

    def test_twice_a_second_with_a_one_second_age(self):
        ctx = FakeContext()
        fw = self.fw(ctx)
        t = 100.0
        for _ in range(240):                  # 4 s of 60 fps frames
            fw._purge_idle_gpu(t)
            t += 1.0 / 60.0
        self.assertIn(len(ctx.calls), (7, 8, 9))
        self.assertTrue(all(c == datetime.timedelta(seconds=GPU_PURGE_IDLE_S) for c in ctx.calls))
        self.assertEqual((GPU_PURGE_IDLE_S, GPU_PURGE_EVERY_S), (1.0, 0.5))

    def test_headless_and_errors_do_nothing(self):
        fw = self.fw(None)
        fw._purge_idle_gpu(50.0)

        class Broken:
            def purgeResourcesNotUsedInMs(self, idle):
                raise RuntimeError("driver")

        fw = self.fw(Broken())
        fw._purge_idle_gpu(60.0)

    def test_zero_turns_it_off(self):
        ctx = FakeContext()
        fw = self.fw(ctx)
        with mock.patch.object(O, "GPU_PURGE_IDLE_S", 0.0):
            for k in range(10):
                fw._purge_idle_gpu(200.0 + k)
        self.assertEqual(ctx.calls, [])


class FakeTexCtx:
    pass


class FakeImage:
    """A decoded image: counts its texture copies."""

    def __init__(self):
        self.copies = []

    def makeTextureImage(self, ctx, mipmapped, budgeted):
        tex = ("texture", ctx, len(self.copies))
        self.copies.append((ctx, mipmapped, budgeted))
        return tex


class FakeSurface:
    def __init__(self, gpu):
        self.gpu = gpu

    def recordingContext(self):
        return object() if self.gpu else None


class FakeCanvas:
    def __init__(self, gpu):
        self.surface = FakeSurface(gpu)

    def getSurface(self):
        return self.surface


class TestPinnedImages(unittest.TestCase):
    def setUp(self):
        from scena import style
        self.style = style
        self.addCleanup(style._drop_pins)
        style._drop_pins()
        self.ctx = FakeTexCtx()
        patch = mock.patch.object(style, "_live_gr_context", lambda: self.ctx)
        patch.start()
        self.addCleanup(patch.stop)

    def pinnable(self):
        img = FakeImage()
        self.style._pinnable(img)
        self.addCleanup(self.style._PINNABLE.pop, id(img), None)
        return img

    def test_a_gpu_canvas_draws_one_held_copy(self):
        import skia
        img = self.pinnable()
        gpu = FakeCanvas(True)
        first = self.style.gpu_image(img, gpu)
        self.assertEqual(first[0], "texture")
        self.assertIs(self.style.gpu_image(img, gpu), first)
        self.assertEqual(len(img.copies), 1)
        # Unbudgeted: pinned images do not crowd Skia's cache budget.
        self.assertEqual(img.copies[0][2], skia.Budgeted.kNo)

    def test_a_raster_canvas_or_a_generated_image_draws_itself(self):
        img = self.pinnable()
        self.assertIs(self.style.gpu_image(img, FakeCanvas(False)), img)
        other = FakeImage()                     # not a decoded file
        self.assertIs(self.style.gpu_image(other, FakeCanvas(True)), other)
        self.assertEqual(other.copies, [])

    def test_a_new_context_makes_a_new_copy(self):
        img = self.pinnable()
        self.style.gpu_image(img, FakeCanvas(True))
        self.style._drop_pins()                 # the window closed
        self.ctx = FakeTexCtx()                 # a second run()
        again = self.style.gpu_image(img, FakeCanvas(True))
        self.assertIs(again[1], self.ctx)
        self.assertEqual(len(img.copies), 2)

    def test_the_switch_draws_the_raster(self):
        img = self.pinnable()
        with mock.patch.object(self.style, "_PIN_IMAGES", False):
            self.assertIs(self.style.gpu_image(img, FakeCanvas(True)), img)

    def test_decoded_files_are_pinnable(self):
        from scena import sprite
        tile = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "examples", "media", "tilesets", "Tiles", "2.png")
        raster = sprite._decode_image(tile)
        self.assertIn(id(raster), self.style._PINNABLE)
        lazy = self.style._load_image(tile)
        self.assertIn(id(lazy), self.style._PINNABLE)

    def test_a_sprite_blit_asks_for_its_draw_image(self):
        from scena import sprite
        from scena.sprite import Sprite
        import skia
        tile = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "examples", "media", "tilesets", "Tiles", "2.png")
        asked = []
        real = sprite.gpu_image

        def spy(img, canvas):
            asked.append(img)
            return real(img, canvas)

        s = Sprite(tile, size=32.0, center=(0, 0))
        self.addCleanup(s.destroy)
        with mock.patch.object(sprite, "gpu_image", spy):
            s._blit_image(skia.Surface(64, 64).getCanvas(), s._blit_paint)
        self.assertEqual(asked, [s._sheet._image_for_frame(0)])


if __name__ == "__main__":
    unittest.main()
