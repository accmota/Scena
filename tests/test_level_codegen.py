"""Copy as code and item.make() build the same shape as the level item.

The editor's "Copy as code" (``level_format.code_for``) and ``LevelItem.make``
share one kind → constructor table. This module evals the copied code in a
Scena world and compares it with ``make()`` and with the item, for every kind
and for random items — the whole class "the copied code / make() does not
reproduce what was drawn".

Run headless:

    python -m unittest tests.test_level_codegen -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from media_support import media  # noqa: E402
from hypothesis import given, strategies as hst  # noqa: E402

import scena  # noqa: E402
from scena import Level, canvas, init  # noqa: E402
from scena.level_format import (  # noqa: E402
    FORMAT, SCOOPS, VERSION, code_for, code_for_items, code_for_sheet, parse,
)

HERE = os.path.dirname(os.path.abspath(__file__))
STAR = media("space", "star_gold.png")


def geometry(shape):
    """Comparable geometry of any shape make() can build."""
    name = type(shape).__name__
    if name in ("Rect", "Ellipse", "Sprite"):
        return (name, round(shape.center.x, 6), round(shape.center.y, 6),
                round(shape.width, 6), round(shape.height, 6), round(shape.angle % 360, 6))
    if name == "Concave":
        return (name, round(shape.center.x, 6), round(shape.center.y, 6),
                round(shape.width, 6), round(shape.height, 6), round(shape.angle % 360, 6),
                shape.scoop, (round(shape.rim.x, 6), round(shape.rim.y, 6)))
    if name == "Circle":
        return (name, round(shape.center.x, 6), round(shape.center.y, 6), round(shape.radius, 6))
    if name == "Line":
        return (name, round(shape.p1.x, 6), round(shape.p1.y, 6),
                round(shape.p2.x, 6), round(shape.p2.y, 6))
    if name == "Polygon":
        return (name, tuple((round(p.x, 6), round(p.y, 6)) for p in shape.points))
    if name == "RegularPolygon":
        return (name, round(shape.center.x, 6), round(shape.center.y, 6),
                round(shape.radius, 6), len(shape.points), round(shape.angle % 360, 6))
    if name == "Triangle":
        return (name, round(shape.center.x, 6), round(shape.center.y, 6),
                round(shape.radius, 6), round(shape.angle % 360, 6), round(shape.base_ratio, 6))
    if name == "Track":
        # A points= Track keeps its vertices about its own center (pose 0 here).
        cx, cy = shape.center.x, shape.center.y
        pts = tuple((round(cx + x, 6), round(cy + y, 6)) for x, y in shape._travel_vertices())
        return (name, pts, shape.closed, round(shape.smooth, 6))
    if name == "Point":
        return (name, round(shape.x, 6), round(shape.y, 6))
    raise AssertionError(name)


def expected(item):
    """The geometry the item describes, straight from the file record."""
    k = item["kind"]
    if k in ("rect", "ellipse", "image"):
        cls = {"rect": "Rect", "ellipse": "Ellipse", "image": "Sprite"}[k]
        return (cls, *item["center"], item["width"], item["height"], item["angle"] % 360)
    if k == "concave":
        return ("Concave", *item["center"], item["width"], item["height"], item["angle"] % 360,
                item["scoop"], tuple(item["rim"]))
    if k == "circle":
        return ("Circle", *item["center"], item["radius"])
    if k == "line":
        return ("Line", *item["p1"], *item["p2"])
    if k == "polygon":
        return ("Polygon", tuple(item["points"]))
    if k == "regular_polygon":
        return ("RegularPolygon", *item["center"], item["radius"], item["n"],
                item["angle"] % 360)
    if k == "triangle":
        return ("Triangle", *item["center"], item["radius"], item["angle"] % 360,
                item["base_ratio"])
    if k == "track":
        return ("Track", tuple(item["points"]), item["closed"], item["smooth"])
    if k == "point":
        return ("Point", *item["center"])
    raise AssertionError(k)


def rounded(t):
    out = []
    for v in t:
        if isinstance(v, float):
            out.append(round(v, 6))
        elif isinstance(v, tuple):
            out.append(rounded(v))
        else:
            out.append(v)
    return tuple(out)


class CodegenCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        self.dir = tempfile.mkdtemp(prefix="test_codegen_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        shutil.copy(STAR, os.path.join(self.dir, "star.png"))

    def check(self, raw):
        """make() == copied code == the item, for one raw item dict."""
        doc = {"format": FORMAT, "version": VERSION, "size": [100, 100], "items": [raw]}
        path = os.path.join(self.dir, "lv.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        item = parse(doc)["items"][0]
        level_item = list(Level(path))[0]
        made = level_item.make()
        ns = {n: getattr(scena, n) for n in scena.__all__}
        old = os.getcwd()
        os.chdir(self.dir)   # the copied line names the image as the file does
        try:
            exec(code_for(item, var="copied"), ns)
        finally:
            os.chdir(old)
        copied = ns["copied"]
        try:
            self.assertEqual(geometry(made), geometry(copied), code_for(item))
            want = rounded(expected(item))
            got = geometry(made)
            if item["kind"] == "track" and item["smooth"]:
                # A smooth track samples a curve through its points: every
                # point lies on it, in order (the curve interpolates them).
                self.assertEqual((got[0], got[2], got[3]), (want[0], want[2], want[3]))
                samples = list(got[1])
                at = 0
                for p in want[1]:
                    self.assertIn(p, samples[at:], code_for(item))
                    at = samples.index(p, at) + 1
            else:
                self.assertEqual(got, want, code_for(item))
            self.assertEqual(set(made.group), set(item["groups"]))
            self.assertEqual(set(copied.group), set(item["groups"]))
        finally:
            made.destroy()
            copied.destroy()


class TestEveryKind(CodegenCase):
    def test_each_kind(self):
        for raw in [
            {"kind": "rect", "center": [450, 170], "width": 220, "height": 24, "angle": 20,
             "groups": ["plataforma"]},
            {"kind": "ellipse", "center": [1, 2], "width": 30, "height": 10, "angle": 45},
            {"kind": "concave", "center": [1, 2], "width": 30, "height": 10},
            {"kind": "concave", "center": [1, 2], "width": 30, "height": 10, "angle": 15,
             "scoop": "right_center", "rim": [4, 4], "groups": ["chao"]},
            {"kind": "concave", "center": [1, 2], "width": 30, "height": 10,
             "scoop": "bottom_left", "rim": [0, 3]},
            {"kind": "circle", "center": [5, 6], "radius": 7, "groups": ["a", "b"]},
            {"kind": "line", "p1": [0, 0], "p2": [10, 5]},
            {"kind": "polygon", "points": [[0, 0], [10, 0], [5, 8]]},
            {"kind": "regular_polygon", "center": [5, 6], "radius": 20, "n": 6},
            {"kind": "regular_polygon", "center": [5, 6], "radius": 20, "n": 3, "angle": 90,
             "groups": ["a"]},
            {"kind": "triangle", "center": [5, 6], "radius": 20},
            {"kind": "triangle", "center": [5, 6], "radius": 20, "angle": 90, "base_ratio": 0.6,
             "groups": ["naves"]},
            {"kind": "track", "points": [[0, 0], [10, 0], [10, 10]], "closed": True},
            {"kind": "track", "points": [[0, 0], [10, 3]]},
            {"kind": "track", "points": [[0, 0], [10, 0], [10, 10]], "smooth": 0.5},
            {"kind": "point", "center": [3, 4], "groups": ["estrela"]},
            {"kind": "image", "file": "star.png", "center": [50, 60], "width": 40,
             "height": 20, "angle": 30},
        ]:
            with self.subTest(kind=raw["kind"]):
                self.check(raw)

    def test_copied_line_uses_the_item_name(self):
        item = parse({"format": FORMAT, "version": VERSION, "size": [1, 1], "items": [
            {"kind": "circle", "name": "moeda", "center": [1, 2], "radius": 3}]})["items"][0]
        self.assertEqual(code_for(item), "moeda = Circle(center=(1, 2), radius=3)")


_c = hst.floats(-2000, 2000, allow_nan=False).map(lambda v: round(v, 2))
_s = hst.floats(1, 500, allow_nan=False).map(lambda v: round(v, 2))
_p = hst.tuples(_c, _c).map(list)
_groups = hst.lists(hst.sampled_from(["g1", "g2", "g3"]), unique=True, max_size=2)


@hst.composite
def _raw_item(draw):
    kind = draw(hst.sampled_from(["rect", "ellipse", "concave", "circle", "line", "polygon",
                                  "regular_polygon", "triangle", "track", "point", "image"]))
    raw = {"kind": kind, "groups": draw(_groups)}
    if kind in ("rect", "ellipse", "concave", "image"):
        raw.update(center=draw(_p), width=draw(_s), height=draw(_s),
                   angle=draw(hst.floats(-359, 359).map(lambda v: round(v, 2))))
    if kind == "concave":
        raw["scoop"] = draw(hst.sampled_from(SCOOPS))
        rim = draw(hst.tuples(_s, _s))
        raw["rim"] = list(rim) if draw(hst.booleans()) else [rim[0], rim[0]]
    if kind == "image":
        raw["file"] = "star.png"
    if kind == "circle":
        raw.update(center=draw(_p), radius=draw(_s))
    if kind == "line":
        raw.update(p1=draw(_p), p2=draw(_p))
    if kind == "polygon":
        raw["points"] = draw(hst.lists(_p, min_size=3, max_size=5, unique_by=tuple))
    if kind == "regular_polygon":
        raw.update(center=draw(_p), radius=draw(_s), n=draw(hst.integers(3, 12)))
        if draw(hst.booleans()):
            raw["angle"] = draw(hst.floats(-359, 359).map(lambda v: round(v, 2)))
    if kind == "triangle":
        raw.update(center=draw(_p), radius=draw(_s))
        if draw(hst.booleans()):
            raw["angle"] = draw(hst.floats(-359, 359).map(lambda v: round(v, 2)))
        if draw(hst.booleans()):
            raw["base_ratio"] = draw(hst.floats(0.05, 1.95).map(lambda v: round(v, 2)))
    if kind == "track":
        raw["points"] = draw(hst.lists(_p, min_size=2, max_size=5, unique_by=tuple))
        raw["closed"] = draw(hst.booleans())
        if draw(hst.booleans()):
            raw["smooth"] = draw(hst.sampled_from([0, 0.25, 0.5, 1]))
    if kind == "point":
        raw["center"] = draw(_p)
    return raw


class TestRandomItems(CodegenCase):
    @given(raw=_raw_item())
    def test_make_and_copied_code_reproduce_the_item(self, raw):
        self.check(raw)



class TestSheetFrames(CodegenCase):
    """A frame image: the copied ``Sheet`` line plus the ``Sprite`` line build
    the frame make() builds, for every layout."""

    SHEETS = [
        {"name": "bola", "file": "rollingBall_sheet.png", "atlas": "rollingBall_sheet.xml"},
        {"name": "fruta", "file": "Cherries.png", "cols": 17},
        {"name": "fruta_cel", "file": "Cherries.png", "cell": [32, 32]},
        {"name": "fruta_grade", "file": "Cherries.png", "cols": 17, "rows": 1},
    ]

    def setUp(self):
        super().setUp()
        for parts in (("k-rolling-ball", "rollingBall_sheet.png"),
                      ("k-rolling-ball", "rollingBall_sheet.xml"), ("pixel_adv", "Cherries.png")):
            shutil.copy(media(*parts), self.dir)

    def check_frame(self, raw):
        doc = {"format": FORMAT, "version": VERSION, "size": [100, 100],
               "sheets": self.SHEETS, "items": [raw]}
        path = os.path.join(self.dir, "lv.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        parsed = parse(doc)
        item = parsed["items"][0]
        made = list(Level(path))[0].make()
        entry = next(e for e in parsed["sheets"] if e["name"] == item["sheet"])
        ns = {n: getattr(scena, n) for n in scena.__all__}
        old = os.getcwd()
        os.chdir(self.dir)
        try:
            exec(code_for_sheet(entry) + "\n" + code_for(item, var="copied"), ns)
        finally:
            os.chdir(old)
        copied = ns["copied"]
        try:
            self.assertEqual(geometry(made), geometry(copied))
            self.assertEqual(geometry(made), rounded(expected(item)))
            self.assertEqual(made.frame, copied.frame)
            self.assertEqual(made.frame, made._sheet.frame_index(item["frame"]))
            self.assertEqual(copied._sheet.nframes, made._sheet.nframes)
            self.assertEqual(set(copied.group), set(item["groups"]))
        finally:
            made.destroy()
            copied.destroy()

    def test_each_layout(self):
        for sheet, frame in (("bola", "block_large.png"), ("bola", 3), ("fruta", 16),
                             ("fruta_cel", 0), ("fruta_grade", 7)):
            with self.subTest(sheet=sheet, frame=frame):
                self.check_frame({"kind": "image", "sheet": sheet, "frame": frame,
                                  "center": [5, 6], "width": 40, "height": 30, "angle": 15,
                                  "groups": ["g"]})

    @given(sheet=hst.sampled_from(["fruta", "fruta_cel", "fruta_grade"]),
           frame=hst.integers(0, 16), center=_p, w=_s, h=_s, groups=_groups)
    def test_random_grid_frames(self, sheet, frame, center, w, h, groups):
        self.check_frame({"kind": "image", "sheet": sheet, "frame": frame, "center": center,
                          "width": w, "height": h, "groups": groups})

    def test_selection_copies_each_sheet_line_once_first(self):
        items = parse({"format": FORMAT, "version": VERSION, "size": [1, 1], "sheets": self.SHEETS,
                       "items": [
                           {"kind": "image", "sheet": "fruta", "frame": 1, "center": [0, 0],
                            "width": 32, "height": 32},
                           {"kind": "point", "name": "p", "center": [1, 1]},
                           {"kind": "image", "sheet": "bola", "frame": "key.png",
                            "center": [0, 0], "width": 32, "height": 32},
                           {"kind": "image", "sheet": "fruta", "frame": 2, "center": [9, 0],
                            "width": 32, "height": 32}]})
        lines = code_for_items(items["items"], items["sheets"]).splitlines()
        self.assertEqual(lines[0], "fruta = Sheet('Cherries.png', cols=17)")
        self.assertEqual(lines[1], "bola = Sheet('rollingBall_sheet.png', atlas='rollingBall_sheet.xml')")
        self.assertEqual(lines[2], "Sprite(fruta, frame=1, center=(0, 0), width=32, height=32)")
        self.assertEqual(len(lines), 6)


if __name__ == "__main__":
    unittest.main()
