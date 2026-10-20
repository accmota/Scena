"""Level files with spritesheets: the ``sheets`` table and frame images.

A sheet entry is one image cut one way, with ``Sheet``'s layouts (``cols`` /
``rows``, ``cell``, ``atlas``); an image item holds a whole ``file`` or a
``sheet`` + ``frame``. ``Level.sheet(name)`` is the one ``Sheet`` every frame
of that sheet uses, built on first use; building it checks every item's frame
(``Sprite(frame="typo")`` only warns, a level raises). Version 2 is always
written; version 1 is still read. Design: Editor Design.md, "File format".

Run headless:

    python -m unittest tests.test_level_sheets -v
"""
import copy
import json
import os
import shutil
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from media_support import MEDIA, media  # noqa: E402
from hypothesis import given, strategies as hst  # noqa: E402

from scena import Level, Sheet, Sprite  # noqa: E402
from scena.level_format import (  # noqa: E402
    FORMAT, VERSION, LevelFormatError, dumps, parse, serialize,
)
from test_level import LevelTestCase, _doc, level_doc  # noqa: E402

BALL_PNG = media("k-rolling-ball", "rollingBall_sheet.png")
BALL_XML = media("k-rolling-ball", "rollingBall_sheet.xml")
CHERRIES = media("pixel_adv", "Cherries.png")          # 544 × 32: 17 frames of 32 px


def sheet_doc(sheets, items, size=(800, 600)):
    return {**level_doc(items, size=size), "sheets": sheets}


BALL = {"name": "bola", "file": "art/rollingBall_sheet.png", "atlas": "art/rollingBall_sheet.xml"}
FRUIT = {"name": "fruta", "file": "art/Cherries.png", "cols": 17}
FRUIT_CELL = {"name": "fruta", "file": "art/Cherries.png", "cell": [32, 32]}


def frame_item(sheet, frame, **extra):
    item = {"kind": "image", "sheet": sheet, "frame": frame, "center": [100, 50],
            "width": 64, "height": 64}
    item.update(extra)
    return item


class TestSheetFormat(unittest.TestCase):
    def bad(self, doc, pattern):
        with self.assertRaisesRegex(LevelFormatError, pattern):
            parse(doc, source="fase1.json")

    def test_table_and_frame_items_parse(self):
        doc = parse(sheet_doc([BALL, FRUIT, FRUIT_CELL | {"name": "fruta2"}], [
            frame_item("bola", "block_large.png"),
            frame_item("fruta", 3),
            {"kind": "image", "file": "fundo.png", "center": [0, 0], "width": 10, "height": 10},
        ]))
        bola, fruta, fruta2 = doc["sheets"]
        self.assertEqual(bola["atlas"], "art/rollingBall_sheet.xml")
        self.assertEqual((fruta["cols"], fruta["rows"], fruta["cell"]), (17, None, None))
        self.assertEqual(fruta2["cell"], (32, 32))
        a, b, c = doc["items"]
        self.assertEqual((a["sheet"], a["frame"], a["file"]), ("bola", "block_large.png", None))
        self.assertEqual((b["frame"], c["file"], c["sheet"]), (3, "fundo.png", None))

    def test_sheet_entry_refusals(self):
        def entry(**raw):
            return sheet_doc([raw], [])
        self.bad(entry(file="a.png", cols=2), "needs 'name'")
        self.bad(entry(name="t", cols=2), "needs 'file'")
        self.bad(entry(name="meu tile", file="a.png", cols=2), "letters, digits and _")
        self.bad(entry(name="1a", file="a.png", cols=2), "letters, digits and _")
        self.bad(entry(name="class", file="a.png", cols=2), "variable name in code")
        self.bad(entry(name="t", file="a.png"), "needs a layout: cols")
        self.bad(entry(name="t", file="a.png", rows=2), "rows needs cols")
        self.bad(entry(name="t", file="a.png", cols=2, cell=[8, 8]), "cols and cell cannot")
        self.bad(entry(name="t", file="a.png", cell=[8, 8], atlas="a.xml"), "cell and atlas")
        self.bad(entry(name="t", file="a.png", cols=0), "whole number >= 1")
        self.bad(entry(name="t", file="a.png", cols=2.5), "whole number >= 1")
        self.bad(entry(name="t", file="a.png", cell=[8.5, 8]), "whole pixels")
        self.bad(entry(name="t", file="a.png", cell=[8]), r"pair \[x, y\]")
        self.bad(entry(name="t", file="a.png", cols=2, fps=8), r"level.sheet\(\"name\"\).clip")
        self.bad(entry(name="t", file="a.png", cols=2, anchor="bottom"), "default anchor")
        self.bad(entry(name="t", file="a.png", cols=2, pixel_size=3), "width and height")
        self.bad(entry(name="t", file="a.png", colls=2), "Did you mean 'cols'")
        self.bad(sheet_doc([BALL, BALL], []), "already used by sheet 0")
        self.bad({**level_doc([]), "sheets": {"bola": BALL}}, "sheets must be a list")

    def test_image_source_refusals(self):
        def one(item, sheets=(BALL,)):
            return sheet_doc(list(sheets), [item])
        base = {"kind": "image", "center": [0, 0], "width": 1, "height": 1}
        self.bad(one(base), "needs 'file' .* or 'sheet' \\+ 'frame'")
        self.bad(one({**base, "file": "a.png", "sheet": "bola", "frame": 0}), "not both")
        self.bad(one({**base, "file": "a.png", "frame": 0}), "not both")
        self.bad(one({**base, "sheet": "bola"}), "'sheet' needs 'frame'")
        for frame, why in ((-1, ">= 0"), (1.5, ">= 0"), (True, ">= 0"), ("", "index or name"),
                           ([0], ">= 0")):
            with self.subTest(frame=frame):
                self.bad(one({**base, "sheet": "bola", "frame": frame}), why)
        self.bad(one({**base, "sheet": "bolla", "frame": 0}), "Did you mean 'bola'")
        self.bad(one({**base, "sheet": "bola", "frame": 0}, sheets=()), "has no sheets")
        self.bad(one({**base, "sheet": "x y", "frame": 0}), "letters, digits and _")

    def test_messages_name_the_file_and_sheet(self):
        self.bad(sheet_doc([{"name": "t", "file": "a.png"}], []), r"fase1.json: sheet 0 \('t'\)")
        self.bad(sheet_doc([BALL], [frame_item("x", 0)]), r"fase1.json: item 0 \(image\)")

    def test_version_2_always_written_version_1_read(self):
        self.assertEqual(VERSION, 2)
        self.assertEqual(serialize(parse(level_doc([])))["version"], 2)
        old = {**level_doc([{"kind": "point", "center": [1, 2]}]), "version": 1}
        self.assertEqual(parse(old)["items"], parse({**old, "version": 2})["items"])

    def test_shipped_version_1_levels_still_load(self):
        for name in ("ninja.json", "duelo.json", "ninja_perigos.json"):
            with self.subTest(level=name):
                with open(media("levels", name), encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(data["version"], 1)
                self.assertEqual(parse(data)["sheets"], [])

    def test_no_sheets_key_when_none_and_one_entry_per_line(self):
        self.assertNotIn("sheets", serialize(parse(level_doc([]))))
        doc = parse(sheet_doc([BALL, FRUIT], [frame_item("bola", "key.png")]))
        text = dumps(serialize(doc))
        self.assertEqual(len(text.splitlines()), 2 + 2 + 1 + 1)
        self.assertEqual(parse(json.loads(text)), doc)
        written = serialize(doc)["sheets"][1]
        self.assertEqual(written, {"name": "fruta", "file": "art/Cherries.png", "cols": 17})


@hst.composite
def _sheet_doc(draw):
    doc = draw(_doc())
    layouts = [{"cols": 4}, {"cols": 4, "rows": 2}, {"cell": [16, 16]}, {"atlas": "a.xml"}]
    sheets = [{"name": f"s{i}", "file": f"s{i}.png", **draw(hst.sampled_from(layouts))}
              for i in range(draw(hst.integers(0, 3)))]
    for item in doc["items"]:
        if item["kind"] == "image" and sheets and draw(hst.booleans()):
            del item["file"]
            item["sheet"] = draw(hst.sampled_from([s["name"] for s in sheets]))
            item["frame"] = draw(hst.one_of(hst.integers(0, 7), hst.sampled_from(["a.png", "b"])))
    return {**doc, "sheets": sheets}


class TestSheetFormatProperties(unittest.TestCase):
    @given(doc=_sheet_doc())
    def test_round_trip_and_canonical(self, doc):
        parsed = parse(doc, source="p.json")
        written = serialize(parsed)
        self.assertEqual(parse(json.loads(dumps(written)), source="p.json"), parsed)
        self.assertEqual(serialize(parse(written)), written)

    @given(doc=_sheet_doc(), data=hst.data())
    def test_a_dangling_sheet_is_an_author_error(self, doc, data):
        i = data.draw(hst.integers(0, len(doc["items"])))
        doc["items"].insert(i, frame_item("nada", 0))
        with self.assertRaises(LevelFormatError) as ctx:
            parse(doc, source="p.json")
        hypothesis_support.assert_author_error(self, ctx.exception, call="parse(level)")
        self.assertIn(f"p.json: item {i}", str(ctx.exception))


class SheetLevelCase(LevelTestCase):
    def setUp(self):
        super().setUp()
        art = os.path.join(self.dir, "art")
        os.makedirs(art)
        for src in (BALL_PNG, BALL_XML, CHERRIES):
            shutil.copy(src, art)

    def level(self, sheets, items):
        return Level(self.write(sheet_doc(copy.deepcopy(sheets), copy.deepcopy(items))))


class TestSheetReader(SheetLevelCase):
    def test_sheets_and_one_catalog_per_sheet(self):
        lv = self.level([BALL, FRUIT], [frame_item("bola", "key.png", name="chave"),
                                        frame_item("fruta", 3, groups=["fruta"]),
                                        frame_item("fruta", 5, groups=["fruta"])])
        self.assertEqual(lv.sheets, ("bola", "fruta"))
        fruit = lv.sheet("fruta")
        self.assertIsInstance(fruit, Sheet)
        self.assertEqual(fruit.nframes, 17)
        a, b = lv.group("fruta")
        self.assertIs(a.sheet, fruit)
        self.assertIs(b.sheet, lv.sheet("fruta"))
        self.assertEqual((a.frame, b.frame, lv["chave"].frame), (3, 5, "key.png"))
        self.assertEqual(lv.sheet("bola").nframes, 59)

    def test_cell_layout_is_the_same_grid(self):
        lv = self.level([FRUIT_CELL], [frame_item("fruta", 16)])
        self.assertEqual(lv.sheet("fruta").nframes, 17)

    def test_make_builds_the_frame_as_drawn(self):
        lv = self.level([FRUIT], [frame_item("fruta", 4, name="c", groups=["fruta"], angle=30,
                                             width=48, height=40)])
        s = self.made(lv["c"].make(layer="ui"))
        self.assertIsInstance(s, Sprite)
        self.assertEqual(s.frame, 4)
        self.assertEqual((s.center.x, s.center.y, s.width, s.height), (100, 50, 48, 40))
        self.assertAlmostEqual(s.angle % 360, 30)
        self.assertIn("fruta", s.group)
        self.assertIs(s._sheet, lv.sheet("fruta"))

    def test_make_refuses_a_frame_keyword(self):
        lv = self.level([FRUIT], [frame_item("fruta", 4, name="c")])
        with self.assertRaisesRegex(TypeError, "remove frame="):
            lv["c"].make(frame=2)

    def test_a_clip_on_the_level_sheet_plays_on_made_frames(self):
        lv = self.level([FRUIT], [frame_item("fruta", 0, name="c")])
        lv.sheet("fruta").clip("gira", list(range(17)), fps=20)
        s = self.made(lv["c"].make())
        s.play("gira")
        self.assertEqual(s._play_name, "gira")

    def test_image_and_frame_fields_are_strict_both_ways(self):
        os.makedirs(os.path.join(self.dir, "arte"), exist_ok=True)
        lv = self.level([FRUIT], [frame_item("fruta", 4, name="c"),
                                  {"kind": "image", "name": "p", "file": "art/Cherries.png",
                                   "center": [0, 0], "width": 10, "height": 10}])
        with self.assertRaisesRegex(AttributeError, r"frame 4 of the sheet 'fruta'.*item.make\(\)"):
            lv["c"].image
        with self.assertRaisesRegex(AttributeError, "whole picture.*item.image"):
            lv["p"].sheet
        with self.assertRaisesRegex(AttributeError, "whole picture.*item.image"):
            lv["p"].frame
        self.assertTrue(lv["p"].image.endswith("Cherries.png"))
        with self.assertRaisesRegex(AttributeError, "has no sheet"):
            Level(self.write(level_doc([{"kind": "point", "name": "x", "center": [0, 0]}]),
                             "p.json"))["x"].sheet

    def test_a_bad_frame_raises_naming_the_item_not_a_warning(self):
        for sheets, item, why in (
            ([BALL], frame_item("bola", "blok_large.png", name="b"), "no frame 'blok_large.png'"),
            ([FRUIT], frame_item("fruta", 17, name="b"), "no frame 17"),
        ):
            with self.subTest(frame=item["frame"]):
                lv = self.level(sheets, [frame_item(sheets[0]["name"], 0 if sheets[0] is FRUIT
                                                    else "key.png"), item])
                with warnings.catch_warnings():
                    warnings.simplefilter("error")
                    with self.assertRaisesRegex(LevelFormatError, rf"fase1.json: item 1 \(image 'b'\).*{why}"):
                        lv["b"].make()
                    with self.assertRaises(LevelFormatError):
                        lv.sheet(sheets[0]["name"])        # every use checks until it builds

    def test_missing_files_show_the_placeholder_not_an_error(self):
        lv = self.level([{"name": "x", "file": "art/nada.png", "cell": [16, 16]},
                         {"name": "y", "file": "art/nada.png", "atlas": "art/nada.xml"}],
                        [frame_item("x", 3, name="a"), frame_item("y", "z.png", name="b")])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            a = self.made(lv["a"].make())
            b = self.made(lv["b"].make())
        self.assertTrue(caught)
        self.assertEqual((a.width, b.height), (64, 64))

    def test_guides_are_dropped_and_not_checked(self):
        lv = self.level([FRUIT], [frame_item("fruta", 99, guide=True), frame_item("fruta", 1)])
        self.assertEqual(len(lv), 1)
        self.assertEqual(lv.sheet("fruta").nframes, 17)

    def test_unknown_sheet_name(self):
        lv = self.level([FRUIT], [])
        with self.assertRaisesRegex(ValueError, "Did you mean 'fruta'"):
            lv.sheet("frutas")
        with self.assertRaisesRegex(ValueError, "no sheets"):
            Level(self.write(level_doc([]), "vazio.json")).sheet("x")
        with self.assertRaises(TypeError):
            lv.sheet(0)

    def test_paths_are_relative_to_the_level_file(self):
        sub = os.path.join(self.dir, "fases")
        os.makedirs(sub)
        doc = sheet_doc([{**FRUIT, "file": "../art/Cherries.png"}], [frame_item("fruta", 2)])
        lv = Level(self.write(doc, os.path.join("fases", "f.json")))
        self.assertEqual(lv.sheet("fruta").nframes, 17)


class TestTrimmedAtlasFrame(SheetLevelCase):
    """A trimmed atlas frame's item box is its untrimmed size, as the Sprite's."""

    def test_untrimmed_box(self):
        import skia
        art = os.path.join(self.dir, "art")
        surf = skia.Surface(20, 10)
        surf.getCanvas().clear(skia.ColorRED)
        surf.makeImageSnapshot().save(os.path.join(art, "t.png"), skia.kPNG)
        atlas = {"frames": {"gema.png": {
            "frame": {"x": 0, "y": 0, "w": 20, "h": 10}, "rotated": False, "trimmed": True,
            "spriteSourceSize": {"x": 6, "y": 11, "w": 20, "h": 10},
            "sourceSize": {"w": 32, "h": 32}}}, "meta": {"image": "t.png"}}
        with open(os.path.join(art, "t.json"), "w") as f:
            json.dump(atlas, f)
        lv = self.level([{"name": "g", "file": "art/t.png", "atlas": "art/t.json"}],
                        [frame_item("g", "gema.png", name="x", width=32, height=32)])
        s = self.made(lv["x"].make())
        self.assertEqual((s.width, s.height), (32, 32))
        self.assertEqual((s.center.x, s.center.y), (100, 50))


if __name__ == "__main__":
    unittest.main()
