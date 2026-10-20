"""Editor: frames of spritesheets in the document, the clipboard and files.

The document keeps the level's sheets with absolute paths, only those some
item uses (undo brings a dropped one back with its item); files write them
relative to the level. A paste into another level reuses a sheet cut the same
way and renames a clash. Choosing a frame keeps the item's center, angle and
scale. Design: Editor Design.md, "Editor (companion app)".

Run: python -m unittest scena_editor.tests.test_editor_sheets
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from media_support import media  # noqa: E402
from scena.level_format import LevelFormatError, parse  # noqa: E402
from scena_editor.doc import LevelDoc, sheet_name_for  # noqa: E402
from scena_editor.tests.test_editor_tools import ed  # noqa: E402

CHERRIES = media("pixel_adv", "Cherries.png")            # 544 × 32: 17 frames of 32 px
BALL_PNG = media("k-rolling-ball", "rollingBall_sheet.png")
BALL_XML = media("k-rolling-ball", "rollingBall_sheet.xml")


def grid(file=CHERRIES, **layout):
    return {"file": file, **(layout or {"cols": 17})}


def frame(sheet, f=0, **extra):
    item = {"kind": "image", "sheet": sheet, "frame": f, "center": (16, 16),
            "width": 32, "height": 32}
    item.update(extra)
    return item


class TestSheetNames(unittest.TestCase):
    def test_names_from_files_are_identifiers(self):
        for file, want in (("Cherries.png", "Cherries"), ("Terrain (16x16).png", "Terrain_16x16"),
                           ("1-bit pack.png", "_1_bit_pack"), ("class.png", "class_"),
                           ("água-viva.png", "água_viva"), ("(().png", "sheet")):
            with self.subTest(file=file):
                name = sheet_name_for(os.path.join("arte", file))
                self.assertEqual(name, want)
                self.assertTrue(name.isidentifier())

    def test_ensure_reuses_the_same_cut_and_names_a_clash(self):
        doc = LevelDoc()
        a = doc.ensure_sheet(grid())
        self.assertEqual(a, "Cherries")
        doc.add(frame(a, 1))
        self.assertEqual(doc.ensure_sheet(grid()), "Cherries")          # same file, same cut
        b = doc.ensure_sheet(grid(cell=[32, 32]))                         # same file, other cut
        self.assertEqual(b, "Cherries_2")
        self.assertEqual(doc.ensure_sheet({**grid(), "name": "fruta"}), "Cherries")
        self.assertEqual(len(doc.sheets), 2)


class TestSheetsInTheDocument(unittest.TestCase):
    def test_two_sheets_then_their_items(self):
        doc = LevelDoc()
        a = doc.ensure_sheet(grid())
        b = doc.ensure_sheet({"file": BALL_PNG, "atlas": BALL_XML})
        doc.add(frame(a, 1))
        doc.add(frame(b, "key.png"))
        self.assertEqual([e["name"] for e in doc.sheets], [a, b])

    def test_an_unused_sheet_yields_its_name(self):
        doc = LevelDoc()
        doc.ensure_sheet(grid())                                         # never used
        self.assertEqual(doc.ensure_sheet(grid(cell=[32, 32])), "Cherries")
        self.assertEqual(len(doc.sheets), 1)

    def test_a_frame_names_a_sheet_of_the_level(self):
        doc = LevelDoc()
        with self.assertRaisesRegex(LevelFormatError, "no sheet named 'x'"):
            doc.add(frame("x"))
        name = doc.ensure_sheet(grid())
        a = doc.add(frame(name, 3))
        self.assertEqual((doc.get(a)["sheet"], doc.get(a)["frame"], doc.get(a)["file"]),
                         (name, 3, None))

    def test_unused_sheets_drop_and_undo_brings_them_back(self):
        e = ed()
        a = e.add_frame(grid(), 2, (32, 32), (0, 0))
        self.assertEqual([s["name"] for s in e.doc.sheets], ["Cherries"])
        e.selection = [a]
        e.delete()
        self.assertEqual(e.doc.to_file_dict().get("sheets"), None)       # not saved
        e.undo()
        self.assertEqual(e.doc.get(a)["sheet"], "Cherries")
        self.assertEqual([s["name"] for s in e.doc.sheets], ["Cherries"])

    def test_add_then_delete_is_clean_again(self):
        e = ed()
        self.assertFalse(e.doc.dirty)
        a = e.add_frame(grid(), 2, (32, 32), (0, 0))
        self.assertTrue(e.doc.dirty)
        e.selection = [a]
        e.delete()
        self.assertFalse(e.doc.dirty)

    def test_add_frame_at_its_pixel_size(self):
        e = ed()
        a = e.add_frame(grid(), 5, (32, 32), (100, 50))
        item = e.doc.get(a)
        self.assertEqual((item["center"], item["width"], item["height"]), ((100, 50), 32, 32))
        self.assertEqual(e.selection, [a])
        self.assertEqual(e.tool, "select")
        e.undo()
        self.assertFalse(e.doc.items)


class TestChooseFrame(unittest.TestCase):
    def test_whole_tileset_becomes_a_tile_at_the_same_scale(self):
        e = ed()
        a = e.doc.add({"kind": "image", "file": CHERRIES, "center": (300, 40),
                       "width": 1088, "height": 64, "angle": 30})       # placed at 2:1
        e.history.commit()
        self.assertTrue(e.set_frame(a, grid(), 4, (32, 32), 32))
        item = e.doc.get(a)
        self.assertEqual((item["file"], item["sheet"], item["frame"]), (None, "Cherries", 4))
        self.assertEqual((item["width"], item["height"]), (64, 64))
        self.assertEqual((item["center"], item["angle"]), ((300, 40), 30))
        e.undo()                                                        # one step
        self.assertEqual(e.doc.get(a)["file"], CHERRIES)
        self.assertEqual(e.doc.sheets, [])                              # restored: none used

    def test_frames_of_other_sizes_keep_their_relative_size(self):
        e = ed()
        atlas = {"file": BALL_PNG, "atlas": BALL_XML}
        a = e.add_frame(atlas, "block_large.png", (64, 64), (0, 0))
        e.doc.update(a, width=32, height=32)                            # 1:2
        self.assertTrue(e.set_frame(a, atlas, "ball_blue_small.png", (32, 32), 64))
        self.assertEqual((e.doc.get(a)["width"], e.doc.get(a)["height"]), (16, 16))

    def test_change_image_turns_a_frame_into_a_whole_picture(self):
        e = ed()
        a = e.add_frame(grid(), 4, (32, 32), (0, 0))
        self.assertTrue(e.replace_image(a, "b.png", (100, 50)))
        item = e.doc.get(a)
        self.assertEqual((item["file"], item["sheet"], item["frame"]), ("b.png", None, None))
        self.assertNotIn("sheets", e.doc.to_file_dict())


class TestClipboard(unittest.TestCase):
    def test_paste_into_another_level_reuses_the_same_cut(self):
        e = ed()
        a = e.add_frame(grid(), 4, (32, 32), (0, 0))
        e.selection = [a]
        e.copy()
        other = LevelDoc()
        other.ensure_sheet({**grid(), "name": "fruta"})
        other.add(frame("fruta", 1))
        e.set_doc(other)
        new = e.paste()
        self.assertEqual(e.doc.get(new[0])["sheet"], "fruta")
        self.assertEqual(len(e.doc.sheets), 1)

    def test_paste_renames_a_clashing_sheet(self):
        e = ed()
        a = e.add_frame(grid(), 4, (32, 32), (0, 0))
        e.selection = [a]
        e.copy()
        other = LevelDoc()
        other.ensure_sheet({**grid(cell=[32, 32]), "name": "Cherries"})
        other.add(frame("Cherries", 1))
        e.set_doc(other)
        new = e.paste()
        self.assertEqual(e.doc.get(new[0])["sheet"], "Cherries_2")
        self.assertEqual(e.doc.sheet("Cherries_2")["cols"], 17)
        self.assertEqual(e.doc.sheet("Cherries")["cell"], (32, 32))

    def test_copy_as_code_prints_the_sheet_first(self):
        e = ed()
        a = e.add_frame(grid(), 4, (32, 32), (0, 0))
        e.selection = [a]
        lines = e.copy().splitlines()
        self.assertTrue(lines[0].startswith("Cherries = Sheet("), lines)
        self.assertIn("cols=17", lines[0])
        self.assertTrue(lines[1].startswith("Sprite(Cherries, frame=4,"), lines)


class TestSheetFiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="test_editor_sheets_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.art = os.path.join(self.dir, "arte")
        os.makedirs(self.art)
        shutil.copy(CHERRIES, self.art)
        shutil.copy(BALL_PNG, self.art)
        shutil.copy(BALL_XML, self.art)

    def doc(self):
        doc = LevelDoc((500, 300))
        g = doc.ensure_sheet(grid(os.path.join(self.art, "Cherries.png")))
        b = doc.ensure_sheet({"file": os.path.join(self.art, "rollingBall_sheet.png"),
                              "atlas": os.path.join(self.art, "rollingBall_sheet.xml")})
        doc.add(frame(g, 3))
        doc.add(frame(b, "key.png", name="chave"))
        return doc

    def test_save_writes_relative_used_sheets_and_load_reads_them_back(self):
        doc = self.doc()
        path = os.path.join(self.dir, "fase.json")
        doc.save(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["sheets"], [
            {"name": "Cherries", "file": "arte/Cherries.png", "cols": 17},
            {"name": "rollingBall_sheet", "file": "arte/rollingBall_sheet.png",
             "atlas": "arte/rollingBall_sheet.xml"}])
        parse(data)
        again = LevelDoc.load(path)
        self.assertEqual(again.sheets, doc.sheets)                      # absolute in memory
        self.assertEqual([{k: v for k, v in i.items() if k != "id"} for i in again.items],
                         [{k: v for k, v in i.items() if k != "id"} for i in doc.items])

    def test_save_as_rebases_sheet_paths(self):
        doc = self.doc()
        doc.save(os.path.join(self.dir, "a.json"))
        sub = os.path.join(self.dir, "fases")
        os.makedirs(sub)
        doc.save(os.path.join(sub, "b.json"))
        with open(os.path.join(sub, "b.json"), encoding="utf-8") as f:
            sheets = json.load(f)["sheets"]
        self.assertEqual(sheets[0]["file"], "../arte/Cherries.png")
        self.assertEqual(sheets[1]["atlas"], "../arte/rollingBall_sheet.xml")

    def test_the_saved_level_loads_in_the_game(self):
        from scena import Level, init
        init(width=400, height=300)
        path = os.path.join(self.dir, "fase.json")
        self.doc().save(path)
        lv = Level(path)
        self.assertEqual(lv.sheet("Cherries").nframes, 17)
        s = lv["chave"].make()
        try:
            self.assertEqual(s.frame, lv.sheet("rollingBall_sheet").frame_index("key.png"))
        finally:
            s.destroy()


if __name__ == "__main__":
    unittest.main()
