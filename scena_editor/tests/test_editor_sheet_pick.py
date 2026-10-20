"""The frame picker on real Scena frames (headless).

Opening the picker borrows the canvas (a backdrop over the level, the sheet
at 1 pixel = 1 unit) and the right panel (the cut); every other widget is
disabled until it closes, when the camera comes back. A click without a drag
picks the frame under the pointer; a drag pans. The cut is ``Sheet``'s, so a
cut it refuses shows its message and picks nothing.

Run: python -m unittest scena_editor.tests.test_editor_sheet_pick
"""
import os
import shutil
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from media_support import media  # noqa: E402
from scena import canvas  # noqa: E402
from scena_editor import _engine, sheet_pick  # noqa: E402
from scena_editor.tests.test_editor_system import EditorSystemCase, world  # noqa: E402
from scena_editor.view import view_point  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made

CHERRIES = media("pixel_adv", "Cherries.png")            # 544 × 32: 17 frames of 32 px
BALL_PNG = media("k-rolling-ball", "rollingBall_sheet.png")
BALL_XML = media("k-rolling-ball", "rollingBall_sheet.xml")


class TestStartLayout(unittest.TestCase):
    def test_what_the_picker_opens_with(self):
        self.assertEqual(sheet_pick.start_layout(BALL_PNG),
                         {"mode": "atlas", "atlas": BALL_XML})       # the atlas beside it
        self.assertEqual(sheet_pick.cell_in_name("Terrain (16x16).png"), (16, 16))
        self.assertEqual(sheet_pick.cell_in_name("Checkpoint (Flag Idle)(64x64).png"), (64, 64))
        self.assertIsNone(sheet_pick.cell_in_name("Cherries.png"))
        self.assertEqual(sheet_pick.start_layout(CHERRIES), {"mode": "whole"})
        entry = {"file": CHERRIES, "cols": 17, "rows": None, "cell": None, "atlas": None}
        self.assertEqual(sheet_pick.start_layout(CHERRIES, entry),
                         {"mode": "grid", "cols": 17, "rows": 1})
        self.assertEqual(sheet_pick.strip_guess(544, 32), {"cols": 17, "rows": 1})
        self.assertEqual(sheet_pick.strip_guess(32, 96), {"cols": 1, "rows": 3})
        self.assertEqual(sheet_pick.strip_guess(100, 70), {"cols": 1, "rows": 1})
        self.assertEqual(sheet_pick.image_for_atlas(BALL_XML), BALL_PNG)

    def test_frame_at_takes_the_smallest_rect(self):
        frames = [((0, 0, 64, 64), (64, 64), "big"), ((10, 10, 8, 8), (8, 8), "small")]
        self.assertEqual(sheet_pick.frame_at(frames, 12, 12), 1)
        self.assertEqual(sheet_pick.frame_at(frames, 40, 40), 0)
        self.assertIsNone(sheet_pick.frame_at(frames, 70, 5))


class PickerCase(EditorSystemCase):
    def setUp(self):
        super().setUp()
        art = os.path.join(self.dir, "arte")
        os.makedirs(art)
        for src in (CHERRIES, BALL_PNG, BALL_XML):
            shutil.copy(src, art)
        self.cherries = os.path.join(art, "Cherries.png")
        self.ball_png = os.path.join(art, "rollingBall_sheet.png")
        self.ball_xml = os.path.join(art, "rollingBall_sheet.xml")

    def click_pixel(self, px, py, h):
        """Click image pixel (px, py) (y down) of a sheet ``h`` pixels high."""
        vx, vy = view_point(px, h - py)
        self.click_view((vx, vy))

    def place_whole(self, path):
        app = self.app
        app._place_image(path)
        self.frame()
        return app.editor.single()


class TestPickFromAtlas(PickerCase):
    def test_atlas_from_the_image_tool_places_the_clicked_frame(self):
        app = self.app
        camera = (canvas.pan_x, canvas.pan_y, canvas.zoom)
        enabled = [w for w in _engine.live_widgets() if w.enabled]
        app._place_image(self.ball_xml)
        self.frame()
        picker = app.picker
        self.assertIsNotNone(picker)
        self.assertEqual(picker.layout["mode"], "atlas")
        self.assertEqual(len(picker.frames), 59)
        own = set(map(id, picker.widgets))
        self.assertFalse([w for w in enabled if id(w) not in own and w.enabled])   # inert panels
        h = picker.img_h
        (x, y, w, hh), size, name = next(f for f in picker.frames if f[2] == "key.png")
        self.click_pixel(x + w / 2, y + hh / 2, h)
        self.assertIsNone(app.picker)
        item = app.editor.single()
        self.assertEqual((item["kind"], item["frame"]), ("image", "key.png"))
        self.assertEqual((item["width"], item["height"]), size)
        self.assertEqual(app.editor.doc.sheet(item["sheet"])["atlas"], self.ball_xml)
        self.assertEqual((canvas.pan_x, canvas.pan_y, canvas.zoom), camera)
        self.assertTrue(all(w.enabled for w in enabled if w.is_alive))
        self.frame()
        self.assertViewMatchesDoc()
        shape = app.view.items[item["id"]].shape
        self.assertEqual(shape.frame, shape._sheet.frame_index("key.png"))

    def test_a_drag_pans_and_picks_nothing(self):
        app = self.app
        app._place_image(self.ball_xml)
        self.frame()
        before = (canvas.pan_x, canvas.pan_y)
        self.drag_view((500, 400), (560, 430))
        self.assertIsNotNone(app.picker)
        self.assertNotEqual((canvas.pan_x, canvas.pan_y), before)
        self.assertEqual(app.editor.doc.items, [])
        app.on_key("ESCAPE")
        self.assertIsNone(app.picker)
        self.assertEqual(app.editor.doc.items, [])


class TestChooseFrame(PickerCase):
    def test_cut_a_placed_strip_into_its_frames(self):
        app = self.app
        item = self.place_whole(self.cherries)
        self.assertEqual((item["width"], item["height"]), (544, 32))
        app.choose_frame()
        self.frame()
        picker = app.picker
        self.assertEqual(picker.layout["mode"], "whole")
        picker.mode_pick.data.value = "Columns × rows"         # the user picks the cut
        self.frame()
        self.assertEqual(picker.layout, {"mode": "grid", "cols": 17, "rows": 1})
        self.assertEqual(len(picker.frames), 17)
        self.click_pixel(5 * 32 + 16, 16, picker.img_h)
        self.assertIsNone(app.picker)
        item = app.editor.single()
        self.assertEqual((item["file"], item["frame"]), (None, 5))
        self.assertEqual((item["width"], item["height"]), (32, 32))       # the same scale
        self.frame()
        self.assertViewMatchesDoc()
        app.undo()
        self.assertEqual(app.editor.doc.items[0]["width"], 544)

    def test_a_refused_cut_shows_the_sheet_message_and_picks_nothing(self):
        app = self.app
        self.place_whole(self.cherries)
        app.choose_frame()
        self.frame()
        picker = app.picker
        picker.mode_pick.data.value = "Cell size"
        self.frame()
        picker.input_a.data.value = 30.0                       # 544 is not a multiple of 30
        self.frame()
        self.assertIn("does not divide", picker.status)
        self.click_pixel(16, 16, picker.img_h)
        self.assertIsNotNone(app.picker)
        self.assertIn("does not divide", app.panel.status.text)
        app.picker.cancel()
        self.assertEqual(app.editor.single()["file"], "arte/Cherries.png")

    def test_choose_frame_on_a_frame_marks_it_and_swaps(self):
        app = self.app
        app._place_image(self.ball_xml)
        self.frame()
        p = app.picker
        (x, y, w, h), _s, _n = next(f for f in p.frames if f[2] == "block_large.png")
        self.click_pixel(x + w / 2, y + h / 2, p.img_h)
        app.choose_frame()
        self.frame()
        p = app.picker
        self.assertTrue(p.mark_current.visible)
        self.assertEqual(p.layout["mode"], "atlas")
        p.filter.data.value = "star"
        self.frame()
        dimmed = [r for r in p._outlines if r.fill is not None]
        self.assertGreater(len(dimmed), 50)
        (x, y, w, h), size, _n = next(f for f in p.frames if f[2] == "star.png")
        self.click_pixel(x + w / 2, y + h / 2, p.img_h)
        item = app.editor.single()
        self.assertEqual(item["frame"], "star.png")
        self.assertEqual(len(app.editor.doc.sheets), 1)

    def test_saved_level_with_picked_frames_loads_in_the_game(self):
        from scena import Level
        app = self.app
        app._place_image(self.ball_xml)
        self.frame()
        p = app.picker
        (x, y, w, h), _s, _n = p.frames[3]
        self.click_pixel(x + w / 2, y + h / 2, p.img_h)
        app.editor.doc.save(os.path.join(self.dir, "fase.json"))
        lv = Level(os.path.join(self.dir, "fase.json"))
        self.assertEqual(lv.sheets, ("rollingBall_sheet",))
        made = lv[list(lv)[0].name] if list(lv)[0].name else None
        it = list(lv)[0]
        s = it.make()
        try:
            self.assertEqual(s.frame, s._sheet.frame_index(it.frame))
        finally:
            s.destroy()


if __name__ == "__main__":
    unittest.main()
