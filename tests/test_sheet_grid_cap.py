"""How many cells a grid ``Sheet`` may have.

A real tileset runs past a thousand cells (Kenney's 1-bit pack: 49 × 22 of
16 px), so the hard cap is 16384 cells. ``cell=`` written where ``cols=`` /
``rows=`` was meant still gets the hint: past 1024 cells with a cell under
8 px on a side. A missing file loaded with a big ``cols=`` / ``rows=`` keeps
its count with a checker of bounded size (one 64 px checker per cell grew
past memory). Design: Sprite Design.md, "Author ladder (Sheet vs Sprite)".

    python -m unittest tests.test_sheet_grid_cap -v
"""
import os
import unittest
import warnings

from scena import Sheet
from scena.sprite import _MAX_GRID_CELLS, _PLACEHOLDER_MAX_SIDE
from tests.test_sprite import SpriteTestCase, _write_rect_png


class TestGridCap(SpriteTestCase):
    def _png(self, w, h, name="sheet.png"):
        path = os.path.join(self._tmp.name, name)
        _write_rect_png(path, w, h)
        return path

    def test_real_tileset_past_a_thousand_cells_loads(self):
        sheet = Sheet(self._png(49 * 16, 22 * 16), cell=(16, 16))
        self.assertEqual(sheet.nframes, 1078)
        self.assertEqual(sheet.frame_index(1077), 1077)

    def test_cols_rows_past_a_thousand_cells_load(self):
        sheet = Sheet(self._png(64 * 2, 32 * 2), cols=64, rows=32)
        self.assertEqual(sheet.nframes, 2048)

    def test_small_cell_typo_keeps_the_cols_rows_hint(self):
        with self.assertRaises(ValueError) as cm:
            Sheet(self._png(400, 300), cell=(4, 3))
        msg = str(cm.exception)
        self.assertIn("cols=4, rows=3", msg)
        self.assertIn("under 8 px", msg)

    def test_small_cells_under_the_typo_count_load(self):
        sheet = Sheet(self._png(128, 128), cell=(4, 4))
        self.assertEqual(sheet.nframes, 1024)

    def test_hard_cap(self):
        side = 129 * 8                          # 129 × 129 = 16641 cells of 8 px
        with self.assertRaises(ValueError) as cm:
            Sheet(self._png(side, side), cell=(8, 8))
        self.assertIn(f"max {_MAX_GRID_CELLS}", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            Sheet(self._png(129, 129), cols=129, rows=129)
        self.assertIn(f"max {_MAX_GRID_CELLS}", str(cm.exception))

    def test_missing_file_big_grid_keeps_count_with_bounded_checker(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sheet = Sheet(os.path.join(self._tmp.name, "absent.png"), cols=120, rows=90)
        self.assertEqual(sheet.nframes, 120 * 90)
        image = sheet.image
        self.assertLessEqual(max(image.width(), image.height()), _PLACEHOLDER_MAX_SIDE)
        self.assertEqual(image.width() % 120, 0)
        self.assertEqual(image.height() % 90, 0)

    def test_missing_file_small_grid_keeps_full_checker(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sheet = Sheet(os.path.join(self._tmp.name, "absent.png"), cols=4, rows=3)
        self.assertEqual((sheet.image.width(), sheet.image.height()), (4 * 64, 3 * 64))


if __name__ == "__main__":
    unittest.main()
