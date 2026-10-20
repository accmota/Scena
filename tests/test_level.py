"""Level files: the format (scena.level_format) and the reader (scena.Level).

Run headless:

    python -m unittest tests.test_level -v
"""
import copy
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

from scena import (  # noqa: E402
    Concave,
    Box, Circle, Ellipse, Level, Line, Point, Polygon, Rect, Sprite, Track, Triangle,
    canvas, group, init,
)
from scena.level_format import (  # noqa: E402
    FORMAT, KINDS, LEGACY_FORMATS, SCOOPS, VERSION, LevelFormatError, parse, serialize,
)

HERE = os.path.dirname(os.path.abspath(__file__))
STAR = media("space", "star_gold.png")


def level_doc(items, size=(3600, 1500)):
    return {"format": FORMAT, "version": VERSION, "size": list(size), "items": items}


SAMPLE_ITEMS = [
    {"kind": "rect", "groups": ["plataforma"], "center": [1000, 150],
     "width": 220, "height": 24, "angle": 20},
    {"kind": "rect", "name": "elevador", "groups": ["plataforma", "especial"],
     "center": [1300, 90], "width": 120, "height": 20},
    {"kind": "ellipse", "name": "lago", "center": [500, 60], "width": 300, "height": 80},
    {"kind": "concave", "name": "rampa", "center": [1600, 100],
     "width": 200, "height": 200, "scoop": "top_right", "rim": [20, 0]},
    {"kind": "circle", "name": "moeda", "center": [10, 10], "radius": 16},
    {"kind": "line", "name": "laser", "p1": [0, 0], "p2": [10, 20]},
    {"kind": "polygon", "name": "morro", "points": [[0, 0], [100, 0], [50, 80]]},
    {"kind": "regular_polygon", "name": "favo", "center": [700, 400], "radius": 30, "n": 6,
     "angle": 90},
    {"kind": "triangle", "name": "nave", "center": [800, 300], "radius": 20, "angle": 90,
     "base_ratio": 0.6},
    {"kind": "track", "name": "rota_drone", "points": [[900, 600], [1300, 600]], "closed": True},
    {"kind": "point", "name": "inicio", "groups": ["spawn"], "center": [120, 70]},
    {"kind": "point", "groups": ["estrela"], "center": [330, 320]},
    {"kind": "image", "name": "fundo", "file": "arte/star.png", "center": [50, 50],
     "width": 40, "height": 30, "angle": 30, "locked": True},
    {"kind": "image", "name": "rascunho", "file": "arte/star.png", "center": [0, 0],
     "width": 10, "height": 10, "guide": True},
]


class LevelTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        self.dir = tempfile.mkdtemp(prefix="test_level_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._made = []
        self.addCleanup(self._destroy_made)

    def _destroy_made(self):
        for s in self._made:
            try:
                s.destroy()
            except Exception:
                pass

    def made(self, shape):
        self._made.append(shape)
        return shape

    def write(self, doc, name="fase1.json"):
        path = os.path.normpath(os.path.join(self.dir, name))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return path

    def sample(self):
        os.makedirs(os.path.join(self.dir, "arte"), exist_ok=True)
        shutil.copy(STAR, os.path.join(self.dir, "arte", "star.png"))
        return Level(self.write(level_doc(copy.deepcopy(SAMPLE_ITEMS))))


class TestReading(LevelTestCase):
    def test_reads_every_kind_in_file_order_without_guides(self):
        lv = self.sample()
        self.assertEqual(len(lv), len(SAMPLE_ITEMS) - 1)
        self.assertEqual([it.kind for it in lv],
                         [i["kind"] for i in SAMPLE_ITEMS if not i.get("guide")])
        self.assertNotIn("rascunho", lv)
        self.assertEqual(lv.size, (3600.0, 1500.0))

    def test_values_are_scena_units_y_up(self):
        lv = self.sample()
        e = lv["elevador"]
        self.assertEqual((e.center.x, e.center.y), (1300.0, 90.0))
        self.assertEqual((e.width, e.height, e.angle), (120.0, 20.0, 0.0))
        self.assertEqual(lv["moeda"].radius, 16.0)
        self.assertEqual((lv["laser"].p2.x, lv["laser"].p2.y), (10.0, 20.0))
        self.assertTrue(lv["rota_drone"].closed)
        self.assertEqual([(p.x, p.y) for p in lv["morro"].points],
                         [(0, 0), (100, 0), (50, 80)])

    def test_center_of_kinds_without_one(self):
        lv = self.sample()
        self.assertEqual((lv["laser"].center.x, lv["laser"].center.y), (5.0, 10.0))
        self.assertEqual((lv["morro"].center.x, lv["morro"].center.y), (50.0, 40.0))

    def test_box_is_oriented_and_fresh(self):
        lv = self.sample()
        item = lv.group("plataforma")[0]
        b = item.box
        self.assertIsInstance(b, Box)
        self.assertAlmostEqual(b.angle, 20.0)
        self.assertEqual((b.width, b.height), (220.0, 24.0))
        # On the long axis of the rotated box (counter-clockwise 20°).
        import math
        a = math.radians(20)
        self.assertTrue(b.contains_point(1000 + 100 * math.cos(a), 150 + 100 * math.sin(a)))
        self.assertFalse(b.contains_point(1000 + 100 * math.cos(a), 150 - 100 * math.sin(a)))
        b.width = 1
        self.assertEqual(item.box.width, 220.0)   # a copy each read

    def test_circle_box_is_its_square(self):
        b = self.sample()["moeda"].box
        self.assertEqual((b.width, b.height), (32.0, 32.0))

    def test_level_box_and_names(self):
        lv = self.sample()
        b = lv.box
        self.assertEqual((b.left, b.bottom, b.right, b.top), (0.0, 0.0, 3600.0, 1500.0))
        self.assertIn("elevador", lv.names)
        self.assertEqual(lv.groups, ("plataforma", "especial", "spawn", "estrela"))

    def test_several_groups_per_item(self):
        lv = self.sample()
        self.assertEqual([it.name for it in lv.group("especial")], ["elevador"])
        self.assertEqual(len(lv.group("plataforma")), 2)
        self.assertEqual(lv["elevador"].groups, ("plataforma", "especial"))

    def test_image_path_is_relative_to_the_level_file(self):
        lv = self.sample()
        self.assertEqual(lv["fundo"].image, os.path.join(self.dir, "arte", "star.png"))

    def test_absolute_image_path_is_kept(self):
        # The editor writes an absolute path only when no relative one exists
        # (another drive on Windows); the reader must not join it to the folder.
        absolute = os.path.join(self.dir, "elsewhere", "x.png")
        lv = Level(self.write(level_doc([{"kind": "image", "name": "x", "file": absolute,
                                          "center": [0, 0], "width": 1, "height": 1}])))
        self.assertEqual(lv["x"].image, os.path.normpath(absolute))

    def test_relative_level_path_found_from_cwd(self):
        self.sample()
        old = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, old)
        self.assertEqual(len(Level("fase1.json")), len(SAMPLE_ITEMS) - 1)


class TestLookupErrors(LevelTestCase):
    def test_unknown_name_suggests(self):
        with self.assertRaisesRegex(ValueError, "Did you mean 'elevador'"):
            self.sample()["elevadr"]

    def test_group_name_used_as_item_name_says_group(self):
        with self.assertRaisesRegex(ValueError, r"is a group: level.group\('plataforma'\)"):
            self.sample()["plataforma"]

    def test_unknown_group_raises_not_empty(self):
        with self.assertRaisesRegex(ValueError, "Did you mean 'plataforma'"):
            self.sample().group("plataform")

    def test_wrong_kind_field_lists_what_it_has(self):
        lv = self.sample()
        with self.assertRaisesRegex(AttributeError, "has no radius. It has: .*width"):
            lv["lago"].radius
        for name in ("laser", "morro", "favo", "rota_drone", "inicio"):
            with self.assertRaisesRegex(AttributeError, "are regions"):
                lv[name].box

    def test_lookup_types(self):
        lv = self.sample()
        with self.assertRaises(TypeError):
            lv[0]
        with self.assertRaises(TypeError):
            lv.group(3)

    def test_missing_file(self):
        with self.assertRaisesRegex(ValueError, "Level file not found"):
            Level(os.path.join(self.dir, "nope.json"))
        with self.assertRaises(TypeError):
            Level(42)

    def test_not_json(self):
        path = os.path.join(self.dir, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{nope")
        with self.assertRaisesRegex(LevelFormatError, "not valid JSON"):
            Level(path)


class TestMake(LevelTestCase):
    def test_make_every_kind_as_drawn(self):
        lv = self.sample()
        r = self.made(lv.group("plataforma")[0].make())
        self.assertIsInstance(r, Rect)
        self.assertEqual((r.center.x, r.center.y, r.width, r.height, r.angle),
                         (1000.0, 150.0, 220.0, 24.0, 20.0))
        self.assertIsInstance(self.made(lv["lago"].make()), Ellipse)
        ramp = self.made(lv["rampa"].make())
        self.assertIsInstance(ramp, Concave)
        self.assertEqual((ramp.scoop, (ramp.rim.x, ramp.rim.y), ramp.width, ramp.height),
                         ("top_right", (20.0, 0.0), 200.0, 200.0))
        self.assertEqual((lv["rampa"].scoop, tuple(lv["rampa"].rim)), ("top_right", (20.0, 0.0)))
        self.assertAlmostEqual(lv["rampa"].box.width, 200.0)
        with self.assertRaisesRegex(AttributeError, "no scoop"):
            lv["lago"].scoop
        c = self.made(lv["moeda"].make())
        self.assertIsInstance(c, Circle)
        self.assertEqual(c.radius, 16.0)
        self.assertIsInstance(self.made(lv["laser"].make()), Line)
        self.assertIsInstance(self.made(lv["morro"].make()), Polygon)
        ship = self.made(lv["nave"].make())
        self.assertIsInstance(ship, Triangle)
        self.assertEqual((ship.center.x, ship.center.y, ship.radius, ship.angle, ship.base_ratio),
                         (800.0, 300.0, 20.0, 90.0, 0.6))
        self.assertEqual((lv["nave"].radius, lv["nave"].angle, lv["nave"].base_ratio),
                         (20.0, 90.0, 0.6))
        with self.assertRaisesRegex(AttributeError, "no base_ratio"):
            lv["favo"].base_ratio
        with self.assertRaisesRegex(AttributeError, "a regular polygon or a triangle"):
            lv["nave"].box
        t = self.made(lv["rota_drone"].make())
        self.assertIsInstance(t, Track)
        self.assertTrue(t.closed)
        p = self.made(lv["inicio"].make())
        self.assertIsInstance(p, Point)
        self.assertEqual((p.x, p.y), (120.0, 70.0))
        s = self.made(lv["fundo"].make())
        self.assertIsInstance(s, Sprite)
        self.assertEqual((s.width, s.height, s.angle), (40.0, 30.0, 30.0))

    def test_make_applies_groups_and_group_adds(self):
        lv = self.sample()
        r = self.made(lv["elevador"].make(group="movel"))
        self.assertEqual(set(r.group), {"plataforma", "especial", "movel"})
        self.assertIn(r, list(group["especial"]))

    def test_make_passes_other_keywords(self):
        r = self.made(self.sample()["elevador"].make(layer="top", color="gold"))
        self.assertEqual(r.layer, "top")

    def test_make_refuses_geometry(self):
        with self.assertRaisesRegex(TypeError, "remove center="):
            self.sample()["lago"].make(center=(0, 0))

    def test_make_twice_gives_two_shapes(self):
        lv = self.sample()
        a = self.made(lv["moeda"].make())
        b = self.made(lv["moeda"].make())
        self.assertIsNot(a, b)


class TestTrackSmooth(LevelTestCase):
    def test_smooth_defaults_to_0_and_make_keeps_it(self):
        lv = Level(self.write(level_doc([
            {"kind": "track", "name": "reta", "points": [[0, 0], [10, 0]]},
            {"kind": "track", "name": "curva", "points": [[0, 0], [10, 0], [10, 10]],
             "smooth": 0.5},
            {"kind": "circle", "name": "moeda", "center": [0, 0], "radius": 1}])))
        self.assertEqual(lv["reta"].smooth, 0.0)
        self.assertEqual(self.made(lv["reta"].make()).smooth, 0.0)   # not Track's 1
        self.assertEqual(lv["curva"].smooth, 0.5)
        self.assertEqual(self.made(lv["curva"].make()).smooth, 0.5)
        with self.assertRaisesRegex(AttributeError, "has no smooth"):
            lv["moeda"].smooth


class TestRegularPolygon(LevelTestCase):
    def test_fields_and_make(self):
        lv = self.sample()
        favo = lv["favo"]
        self.assertEqual((favo.n, favo.radius, favo.angle), (6, 30.0, 90.0))
        self.assertEqual((favo.center.x, favo.center.y), (700.0, 400.0))
        shape = self.made(favo.make())
        self.assertEqual(type(shape).__name__, "RegularPolygon")
        self.assertEqual((len(shape.points), shape.radius, shape.angle), (6, 30.0, 90.0))
        top = max(shape.points, key=lambda p: p.y)          # angle 90: a vertex on top
        self.assertAlmostEqual(top.x, 700.0)
        self.assertAlmostEqual(top.y, 430.0)
        with self.assertRaisesRegex(AttributeError, "has no points"):
            favo.points


class TestLineLengthAngle(LevelTestCase):
    """A line item reads ``length`` and ``angle`` as ``item.make()`` does, so
    the line can be built in another model in one line:
    ``Line(p1=item.p1, angle=item.angle, length=item.length)``."""

    ENDS = (
        ((0, 0), (10, 20)), ((0, 0), (-10, 0)), ((5, 5), (5, -7)), ((3, 4), (3, 4)),
        ((-2, 1), (-9, -6)), ((0, 0), (1e-9, -1)), ((100, 50), (40, 50.000001)),
    )

    def _lines(self):
        items = [{"kind": "line", "name": f"l{i}", "p1": list(a), "p2": list(b)}
                 for i, (a, b) in enumerate(self.ENDS)]
        return Level(self.write(level_doc(items)))

    def test_reads_what_make_reads(self):
        for item in self._lines():
            with self.subTest(p1=item.p1, p2=item.p2):
                line = self.made(item.make())
                self.assertEqual(item.length, line.length)
                self.assertAlmostEqual(item.angle, line.angle, places=9)   # -180, not 180

    def test_rebuilds_the_line_in_another_model(self):
        for item in self._lines():
            with self.subTest(p1=item.p1, p2=item.p2):
                drawn = self.made(item.make())
                for line in (
                    self.made(Line(p1=item.p1, angle=item.angle, length=item.length)),
                    self.made(Line(center=item.center, length=item.length, angle=item.angle)),
                ):
                    for a, b in ((line.p1, drawn.p1), (line.p2, drawn.p2)):
                        self.assertAlmostEqual(a.x, b.x, places=9)
                        self.assertAlmostEqual(a.y, b.y, places=9)

    def test_other_kinds_have_no_length(self):
        lv = self.sample()
        with self.assertRaisesRegex(AttributeError, "has no length. It has: .*width"):
            lv["lago"].length
        self.assertEqual(lv["laser"].angle, self.made(lv["laser"].make()).angle)


class TestFormatErrors(LevelTestCase):
    def bad(self, doc, pattern):
        with self.assertRaisesRegex(LevelFormatError, pattern):
            parse(doc, source="fase1.json")

    def test_not_a_level_file(self):
        self.bad({"items": []}, "not a Scena level file")
        self.bad([1, 2], "not a Scena level file")
        # An unknown tag is still refused (only the listed old spelling is read).
        self.bad({**level_doc([]), "format": "other-level"}, "not a Scena level file")

    def test_newer_version(self):
        self.bad({**level_doc([]), "version": VERSION + 1}, "newer Scena")


    def test_unknown_kind_and_key(self):
        self.bad(level_doc([{"kind": "elipse", "center": [0, 0]}]),
                 "unknown kind 'elipse'. Kinds: rect, .*Did you mean 'ellipse'")
        self.bad(level_doc([{"kind": "circle", "center": [0, 0], "radius": 1, "radious": 2}]),
                 "has no 'radious'.*Did you mean 'radius'")
        self.bad({**level_doc([]), "sizes": [1, 1]}, "unknown top-level key 'sizes'")

    def test_old_rotation_key_names_the_new_one(self):
        self.bad(level_doc([{"kind": "rect", "center": [0, 0], "width": 1, "height": 1,
                             "rotation": 20}]),
                 "'rotation' is now 'angle'")

    def test_old_path_kind_names_the_new_one(self):
        """"path" became "track" (the Scena class it makes): refused with the
        new word — no alias, no silent rewrite."""
        self.bad(level_doc([{"kind": "path", "points": [[0, 0], [1, 1]]}]),
                 "kind 'path' is now 'track'")

    def test_regular_polygon_sides_are_a_whole_number_from_3(self):
        for bad in (2, 5.5, True, "6"):
            self.bad(level_doc([{"kind": "regular_polygon", "center": [0, 0], "radius": 5,
                                 "n": bad}]), "n must be")
        self.bad(level_doc([{"kind": "regular_polygon", "center": [0, 0], "radius": 5}]),
                 "needs 'n'")

    def test_triangle_base_ratio_is_between_0_and_2(self):
        """Triangle(base_ratio=) is open on both ends: 0 is a line, 2 is flat."""
        for bad in (0, 2, -0.5, 2.5, True, "1"):
            self.bad(level_doc([{"kind": "triangle", "center": [0, 0], "radius": 5,
                                 "base_ratio": bad}]), "base_ratio must be")
        self.bad(level_doc([{"kind": "triangle", "center": [0, 0]}]), "needs 'radius'")
        self.bad(level_doc([{"kind": "triangle", "center": [0, 0], "radius": 5, "n": 3}]),
                 "a triangle has no 'n'")

    def test_track_smooth_is_a_fraction(self):
        for bad in (-0.1, 1.5, True, "1"):
            self.bad(level_doc([{"kind": "track", "points": [[0, 0], [1, 1]], "smooth": bad}]),
                     "smooth must be")

    def test_missing_field_negative_size_and_bad_points(self):
        self.bad(level_doc([{"kind": "rect", "center": [0, 0], "width": 1}]), "needs 'height'")
        self.bad(level_doc([{"kind": "circle", "center": [0, 0], "radius": -1}]), ">= 0")
        self.bad(level_doc([{"kind": "polygon", "points": [[0, 0], [1, 1]]}]), "at least 3 points")
        self.bad(level_doc([{"kind": "line", "p1": [0], "p2": [1, 1]}]), r"pair \[x, y\]")

    def test_duplicate_name_and_group(self):
        self.bad(level_doc([{"kind": "point", "name": "a", "center": [0, 0]},
                            {"kind": "point", "name": "a", "center": [1, 1]}]),
                 "already used by item 0")
        self.bad(level_doc([{"kind": "point", "groups": ["g", "g"], "center": [0, 0]}]),
                 "lists 'g' twice")

    def test_messages_name_the_file_and_item(self):
        self.bad(level_doc([{"kind": "point", "name": "x", "center": [0, 0], "angle": 1}]),
                 r"fase1.json: item 0 \(point 'x'\)")


# -- properties --------------------------------------------------------------

_coord = hst.floats(-5000, 5000, allow_nan=False).map(lambda v: round(v, 3))
_size = hst.floats(0, 3000, allow_nan=False).map(lambda v: round(v, 3))
_pt = hst.tuples(_coord, _coord).map(list)
_name_pool = hst.sampled_from(["a", "b", "c", "chao", "inicio"])
_group_pool = hst.lists(hst.sampled_from(["g1", "g2", "plataforma"]), unique=True, max_size=3)


@hst.composite
def _item(draw):
    kind = draw(hst.sampled_from(sorted(KINDS)))
    item = {"kind": kind}
    if kind in ("rect", "ellipse", "concave", "image"):
        item.update(center=draw(_pt), width=draw(_size), height=draw(_size))
        if draw(hst.booleans()):
            item["angle"] = draw(_coord)
    if kind == "concave":
        if draw(hst.booleans()):
            item["scoop"] = draw(hst.sampled_from(SCOOPS))
        if draw(hst.booleans()):
            item["rim"] = [draw(_size), draw(_size)]
    if kind == "image":
        item["file"] = draw(hst.sampled_from(["a.png", "arte/b.png"]))
        if draw(hst.booleans()):
            item["guide"] = draw(hst.booleans())
    if kind == "circle":
        item.update(center=draw(_pt), radius=draw(_size))
    if kind == "line":
        item.update(p1=draw(_pt), p2=draw(_pt))
    if kind in ("polygon", "track"):
        item["points"] = draw(hst.lists(_pt, min_size=3, max_size=6))
    if kind == "track" and draw(hst.booleans()):
        item["closed"] = draw(hst.booleans())
    if kind == "track" and draw(hst.booleans()):
        item["smooth"] = draw(hst.sampled_from([0, 0.5, 1]))
    if kind == "regular_polygon":
        item.update(center=draw(_pt), radius=draw(_size), n=draw(hst.integers(3, 12)))
        if draw(hst.booleans()):
            item["angle"] = draw(_coord)
    if kind == "triangle":
        item.update(center=draw(_pt), radius=draw(_size))
        if draw(hst.booleans()):
            item["angle"] = draw(_coord)
        if draw(hst.booleans()):
            item["base_ratio"] = draw(hst.sampled_from([0.25, 0.6, 1, 1.5, 1.99]))
    if kind == "point":
        item["center"] = draw(_pt)
    groups = draw(_group_pool)
    if groups:
        item["groups"] = groups
    if draw(hst.booleans()):
        item["locked"] = draw(hst.booleans())
    return item


@hst.composite
def _doc(draw):
    items = draw(hst.lists(_item(), max_size=8))
    names = draw(hst.lists(_name_pool, unique=True, max_size=len(items)))
    for item, name in zip(items, names):
        item["name"] = name
    return level_doc(items, size=(draw(_size), draw(_size)))


class TestLegacyFormatTag(LevelTestCase):
    """The framework was Stage before 0.6.0: a ``"stage-level"`` file saved
    then is the same data and still loads; writing always uses ``FORMAT``."""

    def test_the_tag_is_scena_level_and_stage_level_is_legacy(self):
        self.assertEqual(FORMAT, "scena-level")
        self.assertEqual(LEGACY_FORMATS, ("stage-level",))

    def test_an_old_file_parses_like_a_new_one(self):
        new = level_doc(SAMPLE_ITEMS)
        old = {**new, "format": "stage-level"}
        self.assertEqual(parse(old, source="old.json"), parse(new, source="new.json"))

    def test_an_old_file_loads_through_level(self):
        os.makedirs(os.path.join(self.dir, "arte"), exist_ok=True)
        shutil.copy(STAR, os.path.join(self.dir, "arte", "star.png"))
        old = {**level_doc(copy.deepcopy(SAMPLE_ITEMS)), "format": "stage-level"}
        lvl = Level(self.write(old, "antiga.json"))
        self.assertEqual(tuple(lvl.size), (3600, 1500))
        self.assertEqual(lvl["moeda"].kind, "circle")

    def test_writing_uses_the_new_tag(self):
        old = {**level_doc(SAMPLE_ITEMS), "format": "stage-level"}
        self.assertEqual(serialize(parse(old))["format"], "scena-level")


class TestFormatProperties(unittest.TestCase):
    @given(doc=_doc())
    def test_dumps_is_one_item_per_line_and_reads_back(self, doc):
        from scena.level_format import dumps
        parsed = parse(doc, source="p.json")
        text = dumps(serialize(parsed))
        self.assertEqual(parse(json.loads(text), source="p.json"), parsed)
        self.assertEqual(len(text.splitlines()), len(doc["items"]) + 2)

    @given(doc=_doc())
    def test_round_trip(self, doc):
        parsed = parse(doc, source="p.json")
        written = serialize(parsed)
        self.assertEqual(parse(json.loads(json.dumps(written)), source="p.json"), parsed)
        self.assertEqual(serialize(parse(written)), written)   # canonical

    @given(doc=_doc(), data=hst.data())
    def test_one_bad_edit_is_an_author_error(self, doc, data):
        from hypothesis import assume
        assume(doc["items"])
        i = data.draw(hst.integers(0, len(doc["items"]) - 1))
        item = doc["items"][i]
        edit = data.draw(hst.sampled_from(
            ["unknown_key", "drop_required", "wrong_type", "negative", "kind"]))
        required = list(KINDS[item["kind"]]["required"])
        if edit == "unknown_key":
            item["colour"] = 1
        elif edit == "drop_required":
            del item[data.draw(hst.sampled_from(required))]
        elif edit == "wrong_type":
            item[data.draw(hst.sampled_from(required))] = "x" if item["kind"] != "image" else None
        elif edit == "negative":
            sizes = [k for k, v in KINDS[item["kind"]]["required"].items() if v == "size"]
            assume(sizes)
            item[data.draw(hst.sampled_from(sizes))] = -1
        else:
            item["kind"] = "star"         # not a kind (triangle was, until it became one)
        with self.assertRaises(LevelFormatError) as ctx:
            parse(doc, source="p.json")
        hypothesis_support.assert_author_error(self, ctx.exception, call="parse(level)")
        self.assertIn(f"p.json: item {i}", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
