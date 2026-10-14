"""The editor app on real Scena frames (headless): view = document, no leftovers.

Drives ``App`` through the same callbacks ``run()`` wires, steps real frames
(raster draw), and checks that every item has exactly one live Graphic of the
right kind, at the right place, through create / edit / delete / undo / redo
cycles; then that nothing the editor made is left dead in a registry.

Run: python -m unittest scena_editor.tests.test_editor_system
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

from system_support import SystemTestCase  # noqa: E402

from scena import canvas  # noqa: E402
from scena_editor import _engine  # noqa: E402
from scena_editor.app import App  # noqa: E402
from scena_editor.view import DESIGN  # noqa: E402

KIND_CLASS = {"rect": "Rect", "ellipse": "Ellipse", "circle": "Circle", "line": "Line",
              "polygon": "Polygon", "track": "Track", "point": "Circle", "image": "Sprite"}

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def world(vx, vy):
    """View (window) point → world point through the current camera."""
    z = canvas.zoom
    return (vx - DESIGN[0] / 2) / z + canvas.pan_x, (vy - DESIGN[1] / 2) / z + canvas.pan_y


class EditorSystemCase(SystemTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp(prefix="test_editor_system_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(_engine.set_close_guard, None)
        self.app = App(os.path.join(self.dir, "fase.json"))
        self.addCleanup(self._close_prompt)
        from scena_editor.app import callbacks
        # The guarded update, as run() gets it (Scena passes dt and the canvas).
        self.w.fw.update = callbacks(self.app)["update"]
        self.w.step(2)

    def _close_prompt(self):
        # A modal Menu outlives the test (the widget manager is global).
        if self.app._prompt is not None:
            self.app._prompt.destroy()
            self.app._prompt = None

    def frame(self, n=1):
        self.w.step(n)

    def drag_view(self, a, b, steps=4, shift=False):
        app = self.app
        x, y = world(*a)
        app.on_mouse_down(x, y, 0)
        for i in range(1, steps + 1):
            vx = a[0] + (b[0] - a[0]) * i / steps
            vy = a[1] + (b[1] - a[1]) * i / steps
            app.on_mouse_move(*world(vx, vy))
            self.frame()
        x, y = world(*b)
        app.on_mouse_up(x, y, 0, x, y)
        self.frame()

    def click_view(self, p):
        x, y = world(*p)
        self.app.on_mouse_down(x, y, 0)
        self.app.on_mouse_up(x, y, 0, x, y)
        self.frame()

    def assertViewMatchesDoc(self):
        doc = self.app.editor.doc
        views = self.app.view.items
        self.assertEqual(set(views), {i["id"] for i in doc.items})
        for item in doc.items:
            shape = views[item["id"]].shape
            self.assertTrue(shape.is_alive, item)
            self.assertEqual(type(shape).__name__, KIND_CLASS[item["kind"]])
            if "center" in item and item["kind"] != "point":
                self.assertAlmostEqual(shape.center.x, item["center"][0], places=6)
                self.assertAlmostEqual(shape.center.y, item["center"][1], places=6)


class TestEditorOnFrames(EditorSystemCase):
    def test_draw_edit_undo_cycles_keep_the_view_in_step(self):
        app = self.app
        for tool, a, b in (("rect", (300, 300), (420, 360)),
                           ("ellipse", (450, 300), (560, 380)),
                           ("circle", (600, 400), (640, 440)),
                           ("line", (300, 500), (500, 520))):
            app.choose_tool(tool)
            self.drag_view(a, b)
            self.assertViewMatchesDoc()
        app.choose_tool("point")
        self.click_view((700, 300))
        app.choose_tool("polygon")
        for p in ((300, 200), (380, 200), (340, 260)):
            self.click_view(p)
        app.on_key("ENTER")
        self.frame()
        self.assertEqual(len(app.editor.doc.items), 6)
        self.assertViewMatchesDoc()
        # move the polygon, delete it, undo, redo
        self.drag_view((340, 215), (400, 240))
        self.assertViewMatchesDoc()
        app.on_key("DEL")
        self.frame()
        self.assertEqual(len(app.editor.doc.items), 5)
        self.assertViewMatchesDoc()
        for _ in range(3):
            app.editor.undo()
            self.frame()
            self.assertViewMatchesDoc()
        for _ in range(3):
            app.editor.redo()
            self.frame()
            self.assertViewMatchesDoc()

    def test_panel_commit_goes_to_the_item_it_showed(self):
        app = self.app
        ed = app.editor
        a = ed.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        b = ed.doc.add({"kind": "rect", "center": (300, 100), "width": 40, "height": 20})
        ed.history.commit()
        ed.selection = [a]
        self.frame()
        # The user typed a width for A, then clicked B: the commit and the
        # selection change land in the same event, before the panel polls.
        app.panel.fields["width"].input.data.value = 99.0
        ed.selection = [b]
        self.frame()
        self.assertEqual(ed.doc.get(a)["width"], 99.0)
        self.assertEqual(ed.doc.get(b)["width"], 40.0)

    def test_save_shortcut_in_a_focused_field_saves_the_edit(self):
        # Cmd/Ctrl+S used to be swallowed while a panel field had focus; now
        # Scena commits the field and lets the shortcut through.
        import glfw
        app = self.app
        ed = app.editor
        a = ed.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        ed.history.commit()
        ed.selection = [a]
        self.frame()
        box = app.panel.fields["width"].input
        box.focus()
        for c in "77":
            self.w.fw._handle_char(None, ord(c))
        mac = sys.platform == "darwin"
        mod_key = glfw.KEY_LEFT_SUPER if mac else glfw.KEY_LEFT_CONTROL
        mods = glfw.MOD_SUPER if mac else glfw.MOD_CONTROL
        fw = self.w.fw
        fw._handle_key(None, mod_key, 0, glfw.PRESS, mods)
        fw._handle_key(None, glfw.KEY_S, 0, glfw.PRESS, mods)
        self.frame()
        fw._handle_key(None, glfw.KEY_S, 0, glfw.RELEASE, mods)
        fw._handle_key(None, mod_key, 0, glfw.RELEASE, 0)
        self.assertTrue(box.focused)
        self.assertFalse(ed.doc.dirty)
        with open(ed.doc.path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual([i["width"] for i in saved["items"]], [77.0])
        box.text = "5"           # plain keys still type, they do not reach the editor
        fw._handle_key(None, glfw.KEY_F, 0, glfw.PRESS, 0)
        fw._handle_key(None, glfw.KEY_F, 0, glfw.RELEASE, 0)
        self.assertTrue(box.focused)
        self.w.fw.widget_manager.set_focus(None)

    def test_tab_between_panel_fields_commits_and_keeps_focus(self):
        # A commit bumps doc.version and the panel refreshes; refresh used to
        # hide and re-show every field, which dropped the focus Tab had just moved.
        import glfw
        app = self.app
        ed = app.editor
        a = ed.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        ed.history.commit()
        ed.selection = [a]
        self.frame()
        width = app.panel.fields["width"].input
        width.focus()
        fw = self.w.fw
        for c in "55":
            fw._handle_char(None, ord(c))
        fw._handle_key(None, glfw.KEY_TAB, 0, glfw.PRESS, 0)
        fw._handle_key(None, glfw.KEY_TAB, 0, glfw.RELEASE, 0)
        self.frame(2)
        self.assertEqual(ed.doc.get(a)["width"], 55.0)
        focused = fw.widget_manager.focused_widget
        self.assertIsNotNone(focused)
        self.assertIsNot(focused, width)
        self.assertTrue(focused.visible)
        fw.widget_manager.set_focus(None)

    def test_many_groups_field_commits_to_the_items_it_showed(self):
        # Same bug class as the single field: the commit and a new selection
        # land in one event; the edit belongs to the items the field showed.
        app = self.app
        ed = app.editor
        a = ed.doc.add({"kind": "point", "groups": ["robo", "chao"], "center": (0, 0)})
        b = ed.doc.add({"kind": "point", "groups": ["robo"], "center": (50, 0)})
        c = ed.doc.add({"kind": "point", "center": (90, 0)})
        ed.history.commit()
        ed.selection = [a, b]
        self.frame()
        field = app.panel.many["groups"]
        self.assertTrue(field.visible)
        self.assertFalse(app.panel.fields["groups"].visible)
        self.assertEqual(field.input.data.value, "robo")      # what both have
        self.assertTrue(app.panel.some.visible)
        self.assertEqual(str(app.panel.some.text), "Some: chao")
        field.input.data.value = "robo, estrela"
        ed.selection = [c]
        self.frame()
        self.assertEqual(ed.doc.get(a)["groups"], ("robo", "chao", "estrela"))
        self.assertEqual(ed.doc.get(b)["groups"], ("robo", "estrela"))
        self.assertEqual(ed.doc.get(c)["groups"], ())
        self.assertFalse(field.visible)
        self.assertFalse(app.panel.some.visible)

    def test_many_x_field_moves_the_selection(self):
        app = self.app
        ed = app.editor
        a = ed.doc.add({"kind": "point", "center": (0, 0)})
        b = ed.doc.add({"kind": "point", "center": (40, 20)})
        ed.history.commit()
        ed.selection = [a, b]
        self.frame()
        self.assertEqual(app.panel.many["x"].input.data.value, 20.0)
        self.assertEqual(app.panel.many["y"].input.data.value, 10.0)
        app.panel.many["x"].input.data.value = 120.0
        self.frame()
        self.assertEqual(ed.doc.get(a)["center"], (100, 0))
        self.assertEqual(ed.doc.get(b)["center"], (140, 20))

    def test_tab_from_the_many_groups_field_reaches_x_and_keeps_focus(self):
        import glfw
        app = self.app
        ed = app.editor
        ids = [ed.doc.add({"kind": "point", "center": (i * 10, 0)}) for i in range(2)]
        ed.history.commit()
        ed.selection = ids
        self.frame()
        groups = app.panel.many["groups"].input
        groups.focus()
        fw = self.w.fw
        for ch in "g":
            fw._handle_char(None, ord(ch))
        fw._handle_key(None, glfw.KEY_TAB, 0, glfw.PRESS, 0)
        fw._handle_key(None, glfw.KEY_TAB, 0, glfw.RELEASE, 0)
        self.frame(2)
        self.assertTrue(all(ed.doc.get(i)["groups"] == ("g",) for i in ids))
        self.assertIs(fw.widget_manager.focused_widget, app.panel.many["x"].input)
        fw.widget_manager.set_focus(None)

    def test_some_line_is_cut_and_its_tooltip_lists_every_group(self):
        app = self.app
        ed = app.editor
        p = app.panel
        names = [f"grupo_comprido_{i}" for i in range(8)]
        a = ed.doc.add({"kind": "point", "groups": names, "center": (0, 0)})
        b = ed.doc.add({"kind": "point", "center": (50, 0)})
        ed.selection = [a, b]
        now = self._fake_clock()
        self.frame()
        self.assertTrue(str(p.some.text).endswith("…"))
        self.assertLessEqual(p.some.box.right, DESIGN[0])
        self._point(p.some.box.left + 10, (p.some.box.top + p.some.box.bottom) / 2)
        now[0] += p.tooltip.DELAY + 0.1
        self.frame()
        self.assertTrue(p.tooltip.visible)
        self.assertEqual(str(p.tooltip.text.text), ", ".join(names))
        r = p.tooltip.box
        self.assertGreaterEqual(r.center.x - r.width / 2, 0)

    def test_group_frame_and_handles_follow_a_group_turn(self):
        app = self.app
        ed = app.editor
        view = app.view
        a = ed.doc.add({"kind": "rect", "center": (50, 50), "width": 100, "height": 100})
        b = ed.doc.add({"kind": "image", "file": "x.png", "center": (200, 50),
                        "width": 100, "height": 100})
        ed.history.commit()
        ed.selection = [a, b]
        self.frame()
        self.assertTrue(view._group_frame.visible)
        self.assertTrue(view._rotate_knob.visible)
        self.assertEqual(sum(1 for r in view._handles if r.visible), 4)
        knob = next(h for h in ed.handles() if h.role == "group_rotate")
        ed.pointer_down(knob.x, knob.y)
        ed.pointer_move(125 - 100, 50 + 3.5)              # a quarter turn (snapped)
        self.frame()
        self.assertAlmostEqual(float(view._group_frame.angle), 90.0)
        self.assertTrue(all(abs(float(r.angle) - 90.0) < 1e-9 for r in view._handles if r.visible))
        ed.pointer_up(125 - 100, 50 + 3.5)
        self.frame()
        self.assertViewMatchesDoc()
        self.assertAlmostEqual(float(view._group_frame.angle), 0.0)
        ed.selection = [a]
        self.frame()
        self.assertFalse(view._group_frame.visible)

    def test_save_writes_a_level_the_game_reads(self):
        from scena import Level
        app = self.app
        app.choose_tool("rect")
        self.drag_view((300, 300), (420, 360))
        ed = app.editor
        ed.set_field("name", "chao")
        ed.set_field("groups", "plataforma")
        app.save()                                  # has a path: no dialog
        self.frame()
        self.assertFalse(ed.doc.dirty)
        level = Level(ed.doc.path)
        made = level["chao"].make()
        self.track(made)
        self.assertIn("plataforma", made.group)
        with open(ed.doc.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["format"], "scena-level")

    def test_every_button_clicks_through_scena(self):
        """Click each panel Button the way Scena does (widget dispatch, which
        passes the Button to a one-parameter on_click). A crash here is the
        bug class "callback signature vs Scena's call" — the tool buttons once
        received the Button as their tool."""
        from scena.orchestration import ScenaFramework
        from scena.uiwidget import Button
        app = self.app
        started = []
        app.dialogs.start = lambda fn, then: started.append(fn) or True
        a = app.editor.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        wm = ScenaFramework.get_instance().widget_manager
        buttons = [w for w in list(wm.widgets) if isinstance(w, Button) and w.visible]
        self.assertGreaterEqual(len(buttons), 8)   # file 4, Undo / Redo, Fit, 100%
        for btn in buttons:
            app.editor.selection = [a] if app.editor.doc.has(a) else []
            self.frame()
            if not btn.visible:
                continue
            x, y = btn.box.center.x, btn.box.center.y
            wm.handle_mouse_down(x, y, 0)
            wm.handle_mouse_up(x, y, 0)
            self.frame()
            if app._prompt is not None:          # New on a dirty level asks first
                app._prompt.destroy()
                app._prompt = None
        self.assertTrue(started)                 # Open / Save as reached the dialogs

    # -- tool buttons (ui Graphics, not widgets) ----------------------------------------
    def _shape_click(self, x, y):
        """A click as Scena dispatches it to ``ui`` Graphics (view coordinates)."""
        sm = self.w.fw.shape_manager
        self.assertTrue(sm.handle_mouse_down(x, y, 0, ui=True), (x, y))
        sm.handle_mouse_up(x, y, 0, ui=True)

    def _hover(self, x, y):
        self.w.fw.shape_manager.note_pointer(view_xy=(x, y), world_xy=world(x, y))
        self.frame()

    def test_every_tool_button_clicks_through_scena(self):
        """Each icon button (a ui Rect with handlers; the icon and the letter
        have none) chooses its tool through Scena's shape dispatch — the same
        bug class as the Buttons: a callback Scena cannot call, or an icon
        part that takes the click."""
        from scena_editor.tools import TOOLS
        app = self.app
        started = []
        app.dialogs.start = lambda fn, then: started.append(fn) or True
        buttons = {b.tool: b for b in app.panel.tool_buttons}
        self.assertEqual(sorted(buttons), sorted(TOOLS))
        for tool, b in buttons.items():
            if tool in ("select", "image"):
                continue
            x0, y0, x1, y1 = b.box
            for x, y in (((x0 + x1) / 2, (y0 + y1) / 2), (x1 - 4, y0 + 4)):   # icon, letter
                app.choose_tool("select")
                self.frame()
                self._shape_click(x, y)
                self.frame()
                self.assertEqual(app.editor.tool, tool, (x, y))
                self.assertTrue(b.active)
                self.assertFalse(buttons["select"].active)
        x0, y0, x1, y1 = buttons["select"].box
        self._shape_click((x0 + x1) / 2, (y0 + y1) / 2)
        self.frame()
        self.assertEqual(app.editor.tool, "select")
        x0, y0, x1, y1 = buttons["image"].box
        self._shape_click((x0 + x1) / 2, (y0 + y1) / 2)
        self.frame()
        self.assertTrue(started)                 # Image went to the file dialog

    def test_tool_buttons_are_laid_out_apart(self):
        from scena_editor.view import DESIGN, PANEL_LEFT, PANEL_TOP
        p = self.app.panel
        boxes = [b.box for b in p.tool_buttons]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                overlap = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                self.assertFalse(overlap, (a, b))
        for b in p.tool_buttons:
            x0, y0, x1, y1 = b.box
            if b.tool in ("select", "hand"):
                self.assertGreaterEqual(y0, DESIGN[1] - PANEL_TOP)       # top bar
            else:
                self.assertTrue(0 <= x0 and x1 <= PANEL_LEFT, b.tool)  # left toolbar
                self.assertGreater(y0, 0)
        self.assertLess(p.top_bar_right, DESIGN[0])

    def _point(self, x, y):
        """Rest the pointer at a view point: widgets and ui Graphics see it."""
        self.w.fw.widget_manager.handle_mouse_move(x, y)
        self._hover(x, y)

    def _fake_clock(self):
        now = [100.0]
        self.app.panel.tooltip.clock = lambda: now[0]
        return now

    def _over(self, b):
        x0, y0, x1, y1 = b.box
        self._point((x0 + x1) / 2, (y0 + y1) / 2)

    def test_tooltip_waits_then_neighbours_show_at_once(self):
        """Delayed tooltip, then "warm": the next button's tip is immediate
        until the pointer has been off the buttons for COOL seconds."""
        from scena_editor.view import DESIGN
        p = self.app.panel
        tip = p.tooltip
        now = self._fake_clock()
        by = {b.tool: b for b in p.tool_buttons}
        self._over(by["polygon"])
        self.assertFalse(tip.visible)                 # passing over: nothing yet
        now[0] += tip.DELAY - 0.1
        self.frame()
        self.assertFalse(tip.visible)
        now[0] += 0.2
        self.frame()
        self.assertTrue(tip.visible)
        self.assertEqual(tip.text.text, "Polygon (G)")
        self._over(by["track"])                        # warm: at once
        self.assertEqual((tip.visible, tip.text.text), (True, "Track (A)"))
        self._point(DESIGN[0] / 2, DESIGN[1] / 2)     # off the buttons…
        self.assertFalse(tip.visible)
        now[0] += tip.COOL / 2                        # …briefly: still warm
        self._over(by["rect"])
        self.assertEqual((tip.visible, tip.text.text), (True, "Rect (R)"))
        self._point(DESIGN[0] / 2, DESIGN[1] / 2)
        now[0] += tip.COOL + 0.1                      # cooled off: waits again
        self._over(by["ellipse"])
        self.assertFalse(tip.visible)
        now[0] += tip.DELAY + 0.1
        self.frame()
        self.assertEqual((tip.visible, tip.text.text), (True, "Ellipse (E)"))

    def test_a_click_hides_the_tooltip_until_the_pointer_leaves(self):
        from scena_editor.view import DESIGN
        p = self.app.panel
        tip = p.tooltip
        now = self._fake_clock()
        rect = [b for b in p.tool_buttons if b.tool == "rect"][0]
        self._over(rect)
        now[0] += tip.DELAY + 0.1
        self.frame()
        self.assertTrue(tip.visible)
        x0, y0, x1, y1 = rect.box
        self._shape_click((x0 + x1) / 2, (y0 + y1) / 2)
        self.frame()
        self.assertFalse(tip.visible)
        now[0] += 5
        self.frame()
        self.assertFalse(tip.visible)                 # still over it: stays quiet
        self._point(DESIGN[0] / 2, DESIGN[1] / 2)
        self._over(rect)
        now[0] += tip.DELAY + 0.1
        self.frame()
        self.assertTrue(tip.visible)

    def test_every_tooltip_stays_in_the_window_and_off_the_widgets(self):
        """Tool buttons, and every Button with a shortcut, name it; the box is
        inside the window and never under a widget (widgets draw over it)."""
        from scena.orchestration import ScenaFramework
        from scena.uiwidget import Button, CheckBox
        from scena_editor.view import DESIGN
        app = self.app
        p = app.panel
        tip = p.tooltip
        now = self._fake_clock()
        a = app.editor.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        app.editor.selection = [a]                    # the panel shows Duplicate / Delete
        self.frame()
        wm = ScenaFramework.get_instance().widget_manager
        widgets = [w for w in wm.widgets if w.visible]
        expected = {"New": "New (Cmd+N)", "Open…": "Open (Cmd+O)", "Save": "Save (Cmd+S)",
                    "Save as…": "Save as (Cmd+Shift+S)", "Undo": "Undo (Cmd+Z)",
                    "Redo": "Redo (Cmd+Shift+Z)", "Fit": "Fit the level in view (F)",
                    "100%": "Actual size (Cmd+0)", "Duplicate": "Duplicate (Cmd+D)",
                    "Delete": "Delete (Del)"}
        if sys.platform != "darwin":
            expected = {k: v.replace("Cmd+", "Ctrl+") for k, v in expected.items()}
            expected["Redo"] = "Redo (Ctrl+Y)"
        seen = {}
        targets = [(b, b.box) for b in p.tool_buttons]
        targets += [(w, w.box) for w in widgets if isinstance(w, (Button, CheckBox))]
        for owner, box in targets:
            self._point(DESIGN[0] / 2, DESIGN[1] / 2)
            now[0] += 5                               # cold each time
            if isinstance(box, tuple):
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            else:
                cx, cy = box.center.x, box.center.y
            self._point(cx, cy)
            now[0] += tip.DELAY + 0.1
            self.frame()
            label = str(getattr(owner, "label", None) or getattr(owner, "tool", None))
            if not tip.visible:
                seen[label] = None
                continue
            seen[label] = str(tip.text.text)       # a snapshot (the Attribute is live)
            r = tip.box
            x0, x1 = r.center.x - r.width / 2, r.center.x + r.width / 2
            y0, y1 = r.center.y - r.height / 2, r.center.y + r.height / 2
            self.assertTrue(0 <= x0 and x1 <= DESIGN[0] and 0 <= y0 and y1 <= DESIGN[1], label)
            for w in widgets:
                wb = w.box
                under = x0 < wb.right and wb.left < x1 and y0 < wb.top and wb.bottom < y1
                self.assertFalse(under, f"{label!r} tooltip under widget {w!r}")
        for label, text in expected.items():
            self.assertEqual(seen.get(label), text, label)
        self.assertIn("Shift", seen.get(str(app.panel.grid_check.label)) or "")
        for label in ("Copy as code", "Front", "Back"):  # the label says it all
            self.assertIsNone(seen.get(label), label)
        self.assertEqual(seen["polygon"], "Polygon (G)")

    def test_shift_arrow_nudges_by_the_grid_once(self):
        # Scena 0.8.1 delivers Shift+arrow to on_key (Shift no longer blocks a
        # bare key, PD6): one grid step per key event, not a 1-unit nudge too.
        from scena import keyp
        app = self.app
        app.choose_tool("rect")
        self.drag_view((300, 300), (420, 360))
        ed = app.editor
        item = ed.selected_items()[0]
        x0 = item["center"][0]
        tool = ed.tool
        keyp._press("LEFT_SHIFT")
        try:
            app.on_key("RIGHT")
            self.frame()
            app.on_key("R")                          # Shift+letter: no tool switch
            self.frame()
        finally:
            keyp._release("LEFT_SHIFT")
        item = ed.selected_items()[0]
        self.assertAlmostEqual(item["center"][0] - x0, ed.grid)
        self.assertEqual(ed.tool, tool)
        app.on_key("RIGHT")
        self.frame()
        self.assertAlmostEqual(ed.selected_items()[0]["center"][0] - x0, ed.grid + 1.0)

    def test_active_tool_follows_keys_and_creation(self):
        app = self.app
        active = lambda: [b.tool for b in app.panel.tool_buttons if b.active]  # noqa: E731
        self.frame()
        self.assertEqual(active(), ["select"])
        for key, tool in (("H", "hand"), ("R", "rect"), ("P", "point")):
            app.on_key(key)
            self.frame()
            self.assertEqual(active(), [tool])
        app.on_key("ESC")
        self.frame()
        self.assertEqual(active(), ["select"])
        app.choose_tool("rect")
        self.drag_view((300, 300), (420, 360))
        self.frame()
        self.assertEqual(active(), ["select"])     # a create goes back to Select

    def test_holding_primary_shows_select_standby(self):
        """A real Cmd / Ctrl key press: the Select button gets its outline and
        the hint becomes Select's; a Primary+click on a shape selects it in
        the Rect tool; release → back to normal."""
        import glfw
        from scena_editor.i18n import t
        app = self.app
        ed = app.editor
        a = ed.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        ed.history.commit()
        app.choose_tool("rect")
        fw = self.w.fw
        key = glfw.KEY_LEFT_SUPER if sys.platform == "darwin" else glfw.KEY_LEFT_CONTROL
        select = [b for b in app.panel.tool_buttons if b.tool == "select"][0]
        fw._handle_key(None, key, 0, glfw.PRESS, 0)
        self.frame()
        self.assertTrue(ed.select_standby)
        self.assertTrue(select.standby)
        self.assertEqual(ed.hint(), t("hint.select"))
        app.on_mouse_down(100, 100, 0)
        app.on_mouse_up(100, 100, 0, 100, 100)
        self.assertEqual((ed.selection, ed.tool), ([a], "rect"))
        fw._handle_key(None, key, 0, glfw.RELEASE, 0)
        self.frame()
        self.assertFalse(select.standby)
        self.assertEqual(ed.tool, "rect")

    def test_regular_polygon_matches_scena_and_sides_field(self):
        """The editor's vertices are RegularPolygon's (one rule for hit tests
        and drawing); Sides in the panel rebuilds the shape; n < 3 refused."""
        from scena_editor import geometry as geo
        app = self.app
        ed = app.editor
        a = ed.doc.add({"kind": "regular_polygon", "center": (100, 50), "radius": 40, "n": 5,
                        "angle": 30})
        ed.history.commit()
        ed.selection = [a]
        self.frame()
        shape = app.view.items[a].shape
        mine = geo.regular_vertices(ed.doc.get(a))
        for (x, y), p in zip(mine, shape.points):
            self.assertAlmostEqual(x, p.x, places=6)
            self.assertAlmostEqual(y, p.y, places=6)
        field = app.panel.fields["n"]
        self.assertTrue(field.visible)
        self.assertFalse(app.panel.fields["smooth"].visible)
        field.input.data.value = 8.0
        self.frame()
        self.assertEqual(ed.doc.get(a)["n"], 8)
        self.assertEqual(len(app.view.items[a].shape.points), 8)
        field.input.data.value = 2.0
        self.frame()
        self.assertEqual(ed.doc.get(a)["n"], 8)
        self.assertIn("n must be a whole number >= 3", ed.message or "")

    def test_track_smooth_field_redraws_and_rejects_out_of_range(self):
        """The panel's Smooth (tracks only) changes the item and the drawn
        Track; a value outside 0–1 is refused with the format's message."""
        app = self.app
        ed = app.editor
        a = ed.doc.add({"kind": "track", "points": [(0, 0), (100, 0), (100, 100)]})
        ed.history.commit()
        ed.selection = [a]
        self.frame()
        field = app.panel.fields["smooth"]
        self.assertTrue(field.visible)
        self.assertFalse(app.panel.fields["width"].visible)
        field.input.data.value = 0.5
        self.frame()
        self.assertEqual(ed.doc.get(a)["smooth"], 0.5)
        self.assertEqual(app.view.items[a].shape.smooth, 0.5)
        field.input.data.value = 3.0
        self.frame()
        self.assertEqual(ed.doc.get(a)["smooth"], 0.5)
        self.assertIn("smooth must be from 0 to 1", ed.message or "")
        rect = ed.doc.add({"kind": "rect", "center": (0, 0), "width": 10, "height": 10})
        ed.selection = [rect]
        self.frame()
        self.assertFalse(field.visible)

    def test_undo_redo_buttons_follow_history(self):
        app = self.app
        p = app.panel
        self.frame()
        self.assertFalse(p.undo_button.enabled)
        self.assertFalse(p.redo_button.enabled)
        app.choose_tool("rect")
        self.drag_view((300, 300), (420, 360))
        self.frame()
        self.assertTrue(p.undo_button.enabled)
        wm = self.w.fw.widget_manager
        c = p.undo_button.box.center
        wm.handle_mouse_down(c.x, c.y, 0)
        wm.handle_mouse_up(c.x, c.y, 0)
        self.frame()
        self.assertEqual(app.editor.doc.items, [])
        self.assertFalse(p.undo_button.enabled)
        self.assertTrue(p.redo_button.enabled)
        c = p.redo_button.box.center
        wm.handle_mouse_down(c.x, c.y, 0)
        wm.handle_mouse_up(c.x, c.y, 0)
        self.frame()
        self.assertEqual(len(app.editor.doc.items), 1)

    def test_undo_button_lands_a_pending_field_edit_first(self):
        """Typing in a field then clicking Undo in the same frame: the field's
        edit is a step of its own and Undo takes back that one — not the
        step before it, with the edit applied afterwards."""
        import glfw
        app = self.app
        ed = app.editor
        a = ed.doc.add({"kind": "rect", "center": (100, 100), "width": 40, "height": 20})
        ed.history.commit()
        ed.selection = [a]
        self.frame()
        width = app.panel.fields["width"].input
        width.focus()
        fw = self.w.fw
        for ch in "55":
            fw._handle_char(None, ord(ch))
        wm = fw.widget_manager
        c = app.panel.undo_button.box.center
        wm.handle_mouse_down(c.x, c.y, 0)
        wm.handle_mouse_up(c.x, c.y, 0)
        self.frame(2)
        self.assertTrue(ed.doc.has(a))
        self.assertEqual(ed.doc.get(a)["width"], 40.0)
        app.redo()
        self.assertEqual(ed.doc.get(a)["width"], 55.0)
        wm.set_focus(None)

    def test_a_callback_error_is_reported_not_fatal(self):
        from scena_editor.app import guarded
        def boom(*_a):
            raise RuntimeError("boom")
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            guarded(self.app, boom)(1, 2)
        self.assertIn("boom", self.app.note)

    def test_guarded_callbacks_take_what_scena_passes(self):
        """Call every guarded callback the way Scena does (call_truncated, with
        Scena's real argument lists). The guard once took *args, so Scena
        passed update(dt, canvas) to update(dt) — every frame failed."""
        from scena.validate import call_truncated
        from scena_editor.app import callbacks
        x, y = world(640, 400)
        scena_args = {
            "update": (1 / 60, None),
            "on_mouse_down": (x, y, 0),
            "on_mouse_move": (x, y),
            "on_mouse_up": (x, y, 0, x, y),
            "on_mouse_double_click": (x, y, 0),
            "on_mouse_scroll": (0.0, 1.0),
            "on_key": ("V",),
        }
        cbs = callbacks(self.app)
        self.assertEqual(set(cbs), set(scena_args))
        for name, args in scena_args.items():
            call_truncated(cbs[name], *args)
            self.assertEqual(self.app.note, "", name)

    def test_hud_text_and_widgets_do_not_overlap(self):
        """Status-bar parts never overlap (long hints are cut with …), and
        every Button label fits inside its Button."""
        from scena.orchestration import ScenaFramework
        from scena.uiwidget import Button, measure_text
        p = self.app.panel
        self.app.choose_tool("select")
        self.app.say("a very long note " * 12)
        self.frame()
        self.assertLessEqual(p.status.box.right, p.status_right.box.left)
        self.assertLessEqual(p.status_right.box.right, p.status_cursor.box.left)
        self.assertTrue(p.status.text.endswith("…"))
        wm = ScenaFramework.get_instance().widget_manager
        font, pad = wm.widget_theme.default_font, wm.widget_theme.control_pad
        for b in wm.widgets:
            if isinstance(b, Button):
                self.assertLessEqual(measure_text(font, b.label) + 2 * pad, b.width, b.label)

    def test_every_kind_selected_refreshes_the_panel(self):
        """Select one item of each kind (the panel shows its own fields for
        each); nothing may fail. A merge once dropped the helper that shortens
        an image path, so selecting an image raised NameError."""
        app = self.app
        ed = app.editor
        img = os.path.join(self.dir, "arte", "a_very_long_folder_name", "and_a_long_file_name_too.png")
        for raw in ({"kind": "rect", "center": (0, 0), "width": 4, "height": 4},
                    {"kind": "ellipse", "center": (0, 0), "width": 4, "height": 2},
                    {"kind": "circle", "center": (0, 0), "radius": 3},
                    {"kind": "line", "p1": (0, 0), "p2": (5, 5)},
                    {"kind": "polygon", "points": [(0, 0), (5, 0), (2, 4)]},
                    {"kind": "track", "points": [(0, 0), (5, 0)]},
                    {"kind": "point", "center": (1, 1)},
                    {"kind": "image", "file": img, "center": (0, 0), "width": 8, "height": 8}):
            ed.selection = [ed.doc.add(raw)]
            self.frame()
            self.assertEqual(app.note, "", raw["kind"])
        self.assertIn("…", app.panel.image_file.text)

    def test_a_button_error_is_reported_not_fatal(self):
        """A failing Button action is logged and named in the status bar; the
        click returns normally (Scena would end run() on an exception)."""
        import contextlib
        import io
        from unittest import mock
        from scena.orchestration import ScenaFramework
        from scena.uiwidget import Button
        app = self.app
        log_file = os.path.join(self.dir, "editor.log")
        wm = ScenaFramework.get_instance().widget_manager
        fit = [b for b in wm.widgets if isinstance(b, Button) and b.label == "Fit"][0]
        with mock.patch.object(app.editor.viewport, "fit", side_effect=RuntimeError("kaput")), \
                mock.patch("scena_editor.log.log_path", return_value=log_file), \
                contextlib.redirect_stderr(io.StringIO()):
            x, y = fit.box.center.x, fit.box.center.y
            wm.handle_mouse_down(x, y, 0)
            wm.handle_mouse_up(x, y, 0)
        with open(log_file, encoding="utf-8") as f:
            self.assertIn("kaput", f.read())
        self.assertIn(log_file, app.note)          # the status bar names the log

    def test_close_guard_asks_only_when_unsaved(self):
        app = self.app
        self.assertTrue(app._close_guard())
        app.choose_tool("point")
        self.click_view((700, 300))
        self.assertFalse(app._close_guard())
        self.assertIsNotNone(app._prompt)

    def test_no_zombies_after_heavy_editing(self):
        app = self.app
        for i in range(6):
            app.choose_tool("rect")
            self.drag_view((300 + i * 20, 300), (360 + i * 20, 340))
        app.editor.select_all()
        app.editor.delete()
        self.frame()
        for _ in range(4):
            app.editor.undo()
            self.frame()
        self.assertViewMatchesDoc()
        self.assertNoZombies()


if __name__ == "__main__":
    unittest.main()
