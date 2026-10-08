"""Measuring a sprite: ``box`` (the drawn cell), ``hitbox.box``, ``art_box``.

Rule under test (Sprite Design.md, "Measuring a sprite"): every read is a Box
snapshot of the current frame at the current pose. ``box`` is the drawn cell
(padding included) where it is really drawn — pivot, offset, flip and scale
applied. ``sprite.center`` is the pivot, not the middle of the drawing.

Bug class guarded: a measurement built from the pivot or from the size knob
instead of the drawn rect (``anchor="bottom"`` half a height low; ``scale``
ignored).

Fixture: a 64×64 PNG with an opaque 16×48 bar at pixel (24, 8), drawn at
64×64 design units, pivot at (100, 100).

    python -m unittest tests.test_sprite_measure -v
"""
import os
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Box, Sheet, Sprite, canvas, init
from tests.test_sprite import _write_blob_strip, _write_padded_png

PIVOT = (100.0, 100.0)


def lbrt(box):
    return tuple(round(v, 6) for v in (box.left, box.bottom, box.right, box.top))


class MeasureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        cls.png = os.path.join(cls._td.name, "bar.png")
        _write_padded_png(cls.png, canvas_w=64, canvas_h=64, blob=(24, 8, 16, 48))

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        self._owned = []

    def tearDown(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass

    def sprite(self, anchor="center", **kw):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s = Sprite(Sheet(self.png, anchor=anchor), center=PIVOT, width=64, height=64, **kw)
        self._owned.append(s)
        return s


class TestSpriteBoxIsTheDrawnCell(MeasureCase):
    def test_center_anchor(self):
        self.assertEqual(lbrt(self.sprite().box), (68, 68, 132, 132))

    def test_bottom_anchor_sits_on_the_pivot(self):
        """Regression: the box was centred on the pivot (68..132), half a height low."""
        s = self.sprite(anchor="bottom")
        self.assertEqual(lbrt(s.box), (68, 100, 132, 164))
        self.assertEqual(lbrt(Box(s)), (68, 100, 132, 164))

    def test_scale_counts(self):
        """Regression: ``box`` read the size knob and ignored ``scale``."""
        s = self.sprite(anchor="bottom")
        s.scale_by(1.5)
        self.assertEqual(lbrt(s.box), (52, 100, 148, 196))

    def test_offset_moves_the_drawing(self):
        s = self.sprite(offset=(10, -4))
        self.assertEqual(lbrt(s.box), (78, 64, 142, 128))

    def test_flips_keep_the_region(self):
        for flip in ("flip_x", "flip_y"):
            with self.subTest(flip=flip):
                s = self.sprite(anchor="bottom")
                setattr(s, flip, True)
                expect = (68, 100, 132, 164) if flip == "flip_x" else (68, 36, 132, 100)
                self.assertEqual(lbrt(s.box), expect)

    def test_rotation_turns_about_the_pivot(self):
        s = self.sprite(anchor="bottom")
        s.angle = 90                     # up becomes -x (y-up, counter-clockwise)
        self.assertEqual(lbrt(s.box), (36, 68, 100, 132))

    def test_box_holds_the_hitbox(self):
        """The hitbox follows the paint, so it lies inside the drawn cell."""
        for anchor in ("center", "bottom"):
            with self.subTest(anchor=anchor):
                s = self.sprite(anchor=anchor)
                from scena.collision import snapshot_shape
                prims = snapshot_shape(s)
                b = s.box
                self.assertLessEqual(b.left, min(p.aabb[0] for p in prims) + 1e-6)
                self.assertLessEqual(b.bottom, min(p.aabb[1] for p in prims) + 1e-6)
                self.assertGreaterEqual(b.right, max(p.aabb[2] for p in prims) - 1e-6)
                self.assertGreaterEqual(b.top, max(p.aabb[3] for p in prims) - 1e-6)


class TestHitboxAndArtBoxes(MeasureCase):
    TRANSFORMS = (
        ("plain", lambda s: None),
        ("flip_x", lambda s: setattr(s, "flip_x", True)),
        ("flip_y", lambda s: setattr(s, "flip_y", True)),
        ("angle", lambda s: setattr(s, "angle", 90)),
        ("scale", lambda s: s.scale_by(1.5)),
        ("offset", lambda s: setattr(s, "offset", (10, -4))),
    )

    def test_bar_in_padded_cell(self):
        """Hitbox and art are the 16×48 bar; the box is the 64×64 cell."""
        s = self.sprite(anchor="bottom", hitbox_shape="rect")
        self.assertEqual(lbrt(s.box), (68, 100, 132, 164))
        self.assertEqual(lbrt(s.hitbox.box), (92, 108, 108, 156))
        self.assertEqual(lbrt(s.art_box), (92, 108, 108, 156))

    def test_art_box_follows_the_drawing_like_the_hitbox(self):
        """Two independent paths (bake + emit vs art_box) place the bar alike."""
        for anchor in ("center", "bottom"):
            for name, apply in self.TRANSFORMS:
                with self.subTest(anchor=anchor, transform=name):
                    s = self.sprite(anchor=anchor, hitbox_shape="rect")
                    apply(s)
                    self.assertEqual(lbrt(s.art_box), lbrt(s.hitbox.box))
                    b, a = s.box, s.art_box
                    self.assertTrue(b.left - 1e-6 <= a.left and a.right <= b.right + 1e-6)
                    self.assertTrue(b.bottom - 1e-6 <= a.bottom and a.top <= b.top + 1e-6)

    def test_scale_of_the_hitbox_is_not_the_art(self):
        s = self.sprite(hitbox_shape="rect", hitbox_scale=(0.5, 1))
        self.assertAlmostEqual(s.hitbox.box.width, 8.0)
        self.assertAlmostEqual(s.art_box.width, 16.0)

    def test_frames_art_follows_the_cell_frozen_hitbox_does_not(self):
        path = os.path.join(self._td.name, "strip.png")
        _write_blob_strip(path, cell=32, blobs=((12, 20, 8, 8), (4, 4, 24, 24)))
        for source, hitbox_moves in ((0, False), ("each", True)):
            with self.subTest(source=source):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    s = Sprite(Sheet(path, cols=2), center=PIVOT, size=32, frame=0,
                               hitbox_shape="rect", hitbox_source=source)
                self._owned.append(s)
                art0, hb0 = s.art_box.width, s.hitbox.box.width
                s.frame = 1
                self.assertAlmostEqual(art0, 8.0)
                self.assertAlmostEqual(s.art_box.width, 24.0)
                if hitbox_moves:
                    self.assertAlmostEqual(s.hitbox.box.width, 24.0)
                else:
                    self.assertAlmostEqual(s.hitbox.box.width, hb0)

    def test_transparent_cell_art_is_the_box(self):
        path = os.path.join(self._td.name, "clear.png")
        _write_padded_png(path, canvas_w=32, canvas_h=32, blob=(0, 0, 0, 0))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s = Sprite(path, center=PIVOT, size=32)
        self._owned.append(s)
        self.assertEqual(lbrt(s.art_box), lbrt(s.box))

    def test_reads_do_not_enroll(self):
        s = self.sprite()
        s.hitbox.box, s.art_box, s.box
        self.assertIsNone(getattr(s, "_collider", None))


if __name__ == "__main__":
    unittest.main()
