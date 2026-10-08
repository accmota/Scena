"""
TextInput editing (headless): commit rules, scrolling, selection, clipboard,
Esc / Enter / Tab, on_submit, focus(), label, max_length; widget ``enabled``;
DropDown opening upward.

Everything goes through ``WidgetManager`` dispatch (``handle_key`` with
``_key_mods`` set, ``handle_char``, ``handle_mouse_*``), the same path GLFW
events take.

Run:

    python tests/run_tiers.py focused test_text_input
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)

import glfw
import skia
from hypothesis import given, settings, strategies as hs

from scena import Menu, st
from scena.state import DestroyedError
from scena.uiwidget import (
    Button, CheckBox, DropDown, Slider, TextInput, measure_text,
)
from scena import uiwidget as uiw
from tests.test_uiwidget import WidgetTestCase

SHIFT = glfw.MOD_SHIFT
PRIMARY = glfw.MOD_SUPER if sys.platform == "darwin" else glfw.MOD_CONTROL
WORD = glfw.MOD_ALT if sys.platform == "darwin" else glfw.MOD_CONTROL


class TextInputCase(WidgetTestCase):
    def setUp(self):
        super().setUp()
        self.assertIsNone(uiw._scena_window(), "headless: clipboard uses the buffer")
        uiw._clipboard_buffer = ""

    def box(self, cell=None, **kw):
        kw.setdefault("top_left", (20, 300))
        kw.setdefault("width", 200)
        return self.track(TextInput(cell, **kw))

    def cell(self, value):
        name = self.key("ti")
        st.create(name, initial=value)
        return getattr(st, name)

    def press(self, key, mods=0):
        self.wm._key_mods = mods
        try:
            return self.wm.handle_key(key)
        finally:
            self.wm._key_mods = 0

    def type(self, text):
        for c in text:
            self.wm.handle_char(c)

    def focus_by_click(self, box):
        x = box._x2 - 2
        y = (box._y1 + box._y2) / 2
        self.wm.handle_mouse_down(x, y, self.btn)
        self.wm.handle_mouse_up(x, y, self.btn)
        return x, y

    def draw(self, box):
        surface = skia.Surface(1200, 800)
        box.draw(surface.getCanvas())

    def sel(self, box):
        return box._sel_range()


# -- commit rules (bug regressions) -----------------------------------------------------


class TestCommitRules(TextInputCase):
    def test_float_click_in_and_out_keeps_the_value(self):
        # Bug: the box showed f"{v:.2f}" and wrote it back on every focus loss.
        c = self.cell(0.125)
        tb = self.box(c)
        self.wm.set_focus(tb)
        self.wm.set_focus(None)
        self.assertEqual(c.value, 0.125)
        self.assertEqual(tb.text, "0.125")

    @settings(max_examples=60, deadline=None)
    @given(hs.floats(allow_nan=False, allow_infinity=False))
    def test_any_float_survives_focus_in_and_out(self, value):
        c = self.cell(value)
        tb = TextInput(c, top_left=(20, 300), width=200)
        try:
            self.wm.set_focus(tb)
            self.press("ENTER")
            self.wm.set_focus(tb)
            self.wm.set_focus(None)
            self.assertEqual(c.value, value)
        finally:
            tb.destroy()

    def test_bool_cell_is_refused(self):
        # Bug: True showed "1" and the commit stored the string '1'.
        with self.assertRaises(TypeError) as err:
            TextInput(self.cell(True), top_left=(20, 300))
        self.assertIn("CheckBox", str(err.exception))
        with self.assertRaises(TypeError):
            TextInput(initial=False, top_left=(20, 300))

    def test_long_text_is_kept(self):
        # Bug: characters past the box width were dropped.
        tb = self.box(width=100)
        self.wm.set_focus(tb)
        self.type("x" * 200)
        self.assertEqual(len(tb.text), 200)
        self.press("ENTER")
        self.assertEqual(tb.value, "x" * 200)

    def test_invalid_text_stays_visible_and_red(self):
        c = self.cell(10)
        tb = self.box(c)
        self.wm.set_focus(tb)
        self.type("abc")
        self.wm.set_focus(None)
        self.draw(tb)
        self.assertFalse(tb.is_valid)
        self.assertEqual(c.value, 10)
        self.assertEqual(tb.text, "abc")   # focus selected "10"; typing replaced it
        # Editing again clears the red state.
        self.wm.set_focus(tb)
        self.type("1")
        self.assertTrue(tb.is_valid)

    def test_cell_change_replaces_invalid_text(self):
        c = self.cell(10)
        tb = self.box(c)
        self.wm.set_focus(tb)
        self.type("zz")
        self.wm.set_focus(None)
        self.assertFalse(tb.is_valid)
        c.value = 42
        self.draw(tb)
        self.assertTrue(tb.is_valid)
        self.assertEqual(tb.text, "42")

    def test_text_write_before_focus_commits(self):
        c = self.cell("a")
        tb = self.box(c)
        tb.text = "typed by code"
        self.wm.set_focus(tb)
        self.press("ENTER")
        self.assertEqual(c.value, "typed by code")

    def test_focus_right_after_a_cell_write_edits_the_new_value(self):
        # Bug: focus is set before _on_focus_gained, so a "follow the cell
        # unless focused" check skipped and the box edited stale text.
        c = self.cell("old")
        tb = self.box(c)
        c.value = "new"          # no draw in between
        self.wm.set_focus(tb)
        self.assertEqual(tb.text, "new")
        self.wm.set_focus(None)
        self.assertEqual(c.value, "new")

    def test_text_takes_a_str(self):
        tb = self.box()
        with self.assertRaises(TypeError):
            tb.text = 5

    def test_external_write_while_focused_is_not_overwritten(self):
        c = self.cell("old")
        tb = self.box(c)
        self.wm.set_focus(tb)
        c.value = "new"          # the game writes while the box has focus
        self.wm.set_focus(None)  # no edit: nothing to commit
        self.assertEqual(c.value, "new")


class TestFocusInOutNeverChangesAValue(TextInputCase):
    """Bug class: focus in / out with no edit must not change any widget's value."""

    def test_every_value_widget(self):
        cases = [
            (lambda c: Slider(c, top_left=(20, 300), width=200, min_value=0, max_value=1), 0.3333333333),
            (lambda c: DropDown(c, top_left=(20, 300), options=["a", "b"]), "b"),
            (lambda c: CheckBox(c, top_left=(20, 300)), True),
            (lambda c: TextInput(c, top_left=(20, 300)), 0.1 + 0.2),
            (lambda c: TextInput(c, top_left=(20, 300)), 1234567.891011),
            (lambda c: TextInput(c, top_left=(20, 300)), "  spaced  "),
        ]
        for make, value in cases:
            with self.subTest(value=value):
                c = self.cell(value)
                w = self.track(make(c))
                self.wm.set_focus(w)
                self.wm.set_focus(None)
                self.assertEqual(c.value, value)


# -- scrolling ------------------------------------------------------------------------


class TestScrolling(TextInputCase):
    def cursor_x(self, tb):
        return tb._text_x0() + measure_text(tb._theme.default_font, tb.text[:tb._cursor_pos])

    def assert_cursor_inside(self, tb):
        self.draw(tb)
        pad = tb._theme.control_pad
        x = self.cursor_x(tb)
        self.assertGreaterEqual(x, tb._field_x1 + pad - 1e-6)
        self.assertLessEqual(x, tb._x2 - pad + 1e-6)

    def test_cursor_stays_inside(self):
        tb = self.box(width=120)
        self.wm.set_focus(tb)
        self.type("abcdefghij" * 6)
        self.assert_cursor_inside(tb)
        self.assertGreater(tb._scroll_x, 0)
        self.press("HOME")
        self.assert_cursor_inside(tb)
        self.assertEqual(tb._scroll_x, 0)
        self.press("END")
        self.assert_cursor_inside(tb)
        for _ in range(55):
            self.press("BACKSPACE")
        self.assert_cursor_inside(tb)
        self.assertEqual(tb._scroll_x, 0)

    def test_focus_loss_scrolls_back_to_start(self):
        tb = self.box(width=120)
        self.wm.set_focus(tb)
        self.type("abcdefghij" * 6)
        self.draw(tb)
        self.wm.set_focus(None)
        self.draw(tb)
        self.assertEqual(tb._scroll_x, 0)

    def test_click_maps_to_index_while_scrolled(self):
        tb = self.box(width=120)
        self.wm.set_focus(tb)
        self.type("abcdefghij" * 6)
        self.draw(tb)
        font = tb._theme.default_font
        k = 50
        x = tb._text_x0() + measure_text(font, tb.text[:k]) + 0.5
        self.wm.handle_mouse_down(x, (tb._y1 + tb._y2) / 2, self.btn)
        self.wm.handle_mouse_up(x, (tb._y1 + tb._y2) / 2, self.btn)
        self.assertEqual(tb._cursor_pos, k)

    def test_long_value_from_code_is_clipped(self):
        # Drawing never paints past the box: the text is clipped to it.
        c = self.cell("w" * 300)
        tb = self.box(c, width=100)
        surface = skia.Surface(1200, 800)
        canvas = surface.getCanvas()
        canvas.clear(skia.ColorTRANSPARENT)
        tb.draw(canvas)
        pixels = surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        # Nothing right of the box: the text is clipped to it.
        right = int(tb._x2) + 2
        self.assertEqual(int(pixels[:, right:, 3].max()), 0)
        self.assertGreater(int(pixels[:, :right, 3].max()), 0)


# -- selection ------------------------------------------------------------------------


class TestSelection(TextInputCase):
    def make(self, text="hello world"):
        tb = self.box(initial=text, width=300)
        self.wm.set_focus(tb)
        self.press("END")
        return tb

    def x_of(self, tb, i):
        return tb._text_x0() + measure_text(tb._theme.default_font, tb.text[:i])

    def test_focus_selects_all(self):
        tb = self.box(initial="abc")
        self.wm.set_focus(tb)
        self.assertEqual(self.sel(tb), (0, 3))

    def test_shift_arrows_extend(self):
        tb = self.make()
        self.press("LEFT", SHIFT)
        self.press("LEFT", SHIFT)
        self.assertEqual(self.sel(tb), (9, 11))
        self.press("HOME", SHIFT)
        self.assertEqual(self.sel(tb), (0, 11))

    def test_arrow_collapses_selection(self):
        tb = self.make()
        self.press("HOME", SHIFT)
        self.press("RIGHT")
        self.assertEqual(self.sel(tb), (11, 11))
        self.press("HOME", SHIFT)
        self.press("LEFT")
        self.assertEqual(self.sel(tb), (0, 0))

    def test_typing_replaces_selection(self):
        tb = self.make()
        self.press("LEFT", WORD | SHIFT)
        self.assertEqual(self.sel(tb), (6, 11))
        self.type("there")
        self.assertEqual(tb.text, "hello there")

    def test_backspace_and_del_remove_selection(self):
        tb = self.make()
        self.press("HOME")
        self.press("RIGHT", SHIFT)
        self.press("BACKSPACE")
        self.assertEqual(tb.text, "ello world")
        self.press("END", SHIFT)
        self.press("DEL")
        self.assertEqual(tb.text, "")

    def test_word_moves_and_delete(self):
        tb = self.make("one two three")
        self.press("LEFT", WORD)
        self.assertEqual(tb._cursor_pos, 8)
        self.press("LEFT", WORD)
        self.assertEqual(tb._cursor_pos, 4)
        self.press("RIGHT", WORD)
        self.assertEqual(tb._cursor_pos, 7)
        self.press("END")
        self.press("BACKSPACE", WORD)
        self.assertEqual(tb.text, "one two ")

    def test_drag_selects(self):
        tb = self.make()
        y = (tb._y1 + tb._y2) / 2
        self.wm.handle_mouse_down(self.x_of(tb, 2) + 0.5, y, self.btn)
        self.wm.handle_mouse_move(self.x_of(tb, 7) + 0.5, y)
        self.wm.handle_mouse_up(self.x_of(tb, 7) + 0.5, y, self.btn)
        self.assertEqual(self.sel(tb), (2, 7))

    def test_shift_click_extends(self):
        tb = self.make()
        self.press("HOME")
        y = (tb._y1 + tb._y2) / 2
        self.wm._key_mods = SHIFT
        try:
            self.wm.handle_mouse_down(self.x_of(tb, 5) + 0.5, y, self.btn)
            self.wm.handle_mouse_up(self.x_of(tb, 5) + 0.5, y, self.btn)
        finally:
            self.wm._key_mods = 0
        self.assertEqual(self.sel(tb), (0, 5))

    def test_double_click_selects_word(self):
        tb = self.make()
        y = (tb._y1 + tb._y2) / 2
        x = self.x_of(tb, 8) + 0.5
        for _ in range(2):
            self.wm.handle_mouse_down(x, y, self.btn)
            self.wm.handle_mouse_up(x, y, self.btn)
        self.assertEqual(self.sel(tb), (6, 11))

    def test_right_button_does_not_drag(self):
        tb = self.make()
        y = (tb._y1 + tb._y2) / 2
        self.wm.handle_mouse_down(self.x_of(tb, 2) + 0.5, y, glfw.MOUSE_BUTTON_RIGHT)
        self.assertEqual(self.sel(tb), (11, 11))


# -- clipboard ------------------------------------------------------------------------


class TestClipboard(TextInputCase):
    def test_copy_cut_paste(self):
        tb = self.box(initial="hello world", width=300)
        self.wm.set_focus(tb)
        self.press("END")
        self.press("LEFT", WORD | SHIFT)
        self.press("C", PRIMARY)
        self.assertEqual(uiw._clipboard_buffer, "world")
        self.press("X", PRIMARY)
        self.assertEqual(tb.text, "hello ")
        self.press("V", PRIMARY)
        self.press("V", PRIMARY)
        self.assertEqual(tb.text, "hello worldworld")

    def test_select_all(self):
        tb = self.box(initial="abc")
        self.wm.set_focus(tb)
        self.press("END")
        self.press("A", PRIMARY)
        self.assertEqual(self.sel(tb), (0, 3))

    def test_paste_is_one_line(self):
        tb = self.box()
        self.wm.set_focus(tb)
        uiw._clipboard_buffer = "a\r\nb\nc\td"
        self.press("V", PRIMARY)
        self.assertEqual(tb.text, "a b cd")

    def test_paste_respects_max_length(self):
        tb = self.box(max_length=5)
        self.wm.set_focus(tb)
        self.type("ab")
        uiw._clipboard_buffer = "123456789"
        self.press("V", PRIMARY)
        self.assertEqual(tb.text, "ab123")

    def test_linked_box_copies_but_does_not_edit(self):
        st.create("ti_title", initial="hero")
        tb = self.box(initial="x")
        tb["data"] @= st.ti_title
        self.wm.set_focus(tb)
        self.press("C", PRIMARY)
        self.assertEqual(uiw._clipboard_buffer, "hero")
        self.press("X", PRIMARY)
        self.press("V", PRIMARY)
        self.type("z")
        self.press("BACKSPACE")
        self.assertEqual(tb.text, "hero")


# -- Esc / Enter / on_submit ------------------------------------------------------------


class TestEscAndSubmit(TextInputCase):
    def test_esc_cancels_and_unfocuses(self):
        c = self.cell("Ana")
        seen = []
        tb = self.box(c, on_submit=seen.append)
        self.wm.set_focus(tb)
        self.press("END")
        self.type("b")
        self.press("ESC")
        self.assertFalse(tb.focused)
        self.assertEqual(c.value, "Ana")
        self.assertEqual(tb.text, "Ana")
        self.assertEqual(seen, [])

    def test_esc_clears_red_state(self):
        c = self.cell(3)
        tb = self.box(c)
        self.wm.set_focus(tb)
        self.type("x")
        self.wm.set_focus(None)
        self.assertFalse(tb.is_valid)
        self.wm.set_focus(tb)
        self.press("ESC")
        self.assertTrue(tb.is_valid)
        self.assertEqual(tb.text, "3")

    def test_esc_with_nothing_focused_reaches_the_game(self):
        self.box()
        self.wm.set_focus(None)
        self.assertFalse(self.wm.handle_key("ESC"))

    def test_on_submit_arity(self):
        got = []
        tb = self.box(self.cell("x"), on_submit=lambda: got.append("none"))
        self.wm.set_focus(tb)
        self.press("ENTER")
        tb.on_submit = lambda v: got.append(v)
        self.wm.set_focus(tb)
        self.press("ENTER")      # unchanged text still submits
        self.assertEqual(got, ["none", "x"])
        with self.assertRaises(TypeError):
            tb.on_submit = lambda a, b: None

    def test_on_submit_gets_the_converted_value(self):
        got = []
        tb = self.box(self.cell(1), on_submit=got.append)
        self.wm.set_focus(tb)
        self.type("42")
        self.press("ENTER")
        self.assertEqual(got, [42])
        self.assertFalse(tb.focused)

    def test_no_submit_on_click_away_or_bad_number(self):
        got = []
        tb = self.box(self.cell(1), on_submit=got.append)
        self.wm.set_focus(tb)
        self.type("7")
        self.wm.set_focus(None)
        self.wm.set_focus(tb)
        self.type("nope")
        self.press("ENTER")
        self.assertEqual(got, [])
        self.assertFalse(tb.is_valid)

    def test_console_keeps_typing_with_focus(self):
        lines = []

        def run(cmd):
            lines.append(cmd)
            console.text = ""
            console.focus()

        console = self.box(on_submit=run)
        console.focus()
        self.type("help")
        self.press("ENTER")
        self.assertTrue(console.focused)
        self.type("quit")
        self.press("ENTER")
        self.assertEqual(lines, ["help", "quit"])


# -- focus() / Tab ------------------------------------------------------------------------


class TestFocusAndTab(TextInputCase):
    def three(self):
        cells = [self.cell(n) for n in ("a", "b", "c")]
        boxes = [self.box(c, top_left=(20, 400 - 40 * i)) for i, c in enumerate(cells)]
        return cells, boxes

    def test_focus_method(self):
        tb = self.box(initial="abc")
        self.assertIs(tb.focus(), tb)
        self.assertTrue(tb.focused)
        self.assertEqual(self.sel(tb), (0, 3))

    def test_focus_refusals(self):
        hidden = self.box()
        hidden.visible = False
        with self.assertRaises(RuntimeError):
            hidden.focus()
        off = self.box(enabled=False)
        with self.assertRaises(RuntimeError):
            off.focus()
        gone = TextInput(top_left=(20, 300))
        gone.destroy()
        with self.assertRaises(DestroyedError):
            gone.focus()
        tb = self.box()
        menu = Menu(options=["ok"])
        try:
            with self.assertRaises(RuntimeError):
                tb.focus()
        finally:
            menu.destroy()

    def test_tab_order_wraps_and_commits(self):
        cells, (a, b, c) = self.three()
        a.focus()
        self.type("1")
        self.press("TAB")
        self.assertTrue(b.focused)
        self.assertEqual(cells[0].value, "1")
        self.assertEqual(self.sel(b), (0, 1))
        self.press("TAB")
        self.press("TAB")
        self.assertTrue(a.focused)
        self.press("TAB", SHIFT)
        self.assertTrue(c.focused)

    def test_tab_skips_hidden_and_disabled(self):
        _, (a, b, c) = self.three()
        b.visible = False
        a.focus()
        self.press("TAB")
        self.assertTrue(c.focused)
        b.visible = True
        b.enabled = False
        self.press("TAB", SHIFT)
        self.assertTrue(a.focused)

    def test_tab_alone_stays(self):
        tb = self.box()
        tb.focus()
        self.press("TAB")
        self.assertTrue(tb.focused)


# -- label / max_length ----------------------------------------------------------------


class TestLabelAndMaxLength(TextInputCase):
    def test_label_shares_slider_column(self):
        s = self.track(Slider(label="Speed", width=300))
        tb = self.track(TextInput(label="Player name", width=300))
        self.assertAlmostEqual(s._x1, tb._x1)
        self.assertAlmostEqual(tb._field_x1 - tb._x1, s._label_space)
        self.assertGreater(tb._field_x1, tb._x1)

    def test_no_label_field_starts_at_x1(self):
        tb = self.box()
        self.assertEqual(tb._field_x1, tb._x1)

    def test_max_length(self):
        tb = self.box(max_length=3)
        tb.focus()
        self.type("abcdef")
        self.assertEqual(tb.text, "abc")
        self.press("A", PRIMARY)
        self.type("z")          # replacing a selection makes room
        self.assertEqual(tb.text, "z")

    def test_max_length_validated(self):
        for bad, err in ((0, ValueError), (2.5, TypeError), (True, TypeError), ("3", TypeError)):
            with self.subTest(bad=bad), self.assertRaises(err):
                TextInput(top_left=(20, 300), max_length=bad)


# -- enabled ---------------------------------------------------------------------------


class TestEnabled(TextInputCase):
    def test_disabled_button_swallows_the_click(self):
        clicks = []
        b = self.track(Button(label="Save", top_left=(20, 300), on_click=lambda: clicks.append(1),
                              enabled=False))
        x, y = (b._x1 + b._x2) / 2, (b._y1 + b._y2) / 2
        self.assertTrue(self.wm.handle_mouse_down(x, y, self.btn))   # game does not get it
        self.assertTrue(self.wm.handle_mouse_up(x, y, self.btn))
        self.assertEqual(clicks, [])
        b.enabled = True
        self.click(b)
        self.assertEqual(clicks, [1])

    def test_disabled_still_hover_target_without_highlight(self):
        b = self.track(Button(label="Save", top_left=(20, 300), enabled=False))
        x, y = (b._x1 + b._x2) / 2, (b._y1 + b._y2) / 2
        self.assertTrue(self.wm.handle_mouse_move(x, y))
        self.assertIs(self.wm.mouse_over_widget, b)
        self.assertFalse(b._is_mouse_over)

    def test_disabling_focused_box_commits(self):
        c = self.cell("a")
        tb = self.box(c)
        tb.focus()
        self.type("b")
        tb.enabled = False
        self.assertFalse(tb.focused)
        self.assertEqual(c.value, "b")

    def test_disabled_slider_ignores_scroll(self):
        c = self.cell(50.0)
        s = self.track(Slider(c, top_left=(20, 300), width=200, enabled=False))
        x, y = (s._x1 + s._x2) / 2, (s._y1 + s._y2) / 2
        self.assertTrue(self.wm.handle_mouse_scroll(x, y, 0, 1))
        self.assertEqual(c.value, 50.0)

    def test_disabled_draws(self):
        self.track(CheckBox(top_left=(20, 300), enabled=False))
        self.wm.draw(skia.Surface(1200, 800).getCanvas())

    def test_menu_refuses_enabled(self):
        menu = Menu(options=["ok"])
        try:
            with self.assertRaises(AttributeError) as err:
                menu.enabled = False
            self.assertIn("destroy()", str(err.exception))
        finally:
            menu.destroy()

    def test_enabled_knob_on_every_widget(self):
        for make in (lambda: Button(top_left=(20, 300), enabled=False),
                     lambda: CheckBox(top_left=(20, 300), enabled=False),
                     lambda: Slider(top_left=(20, 300), enabled=False),
                     lambda: DropDown(top_left=(20, 300), enabled=False),
                     lambda: TextInput(top_left=(20, 300), enabled=False)):
            w = self.track(make())
            self.assertFalse(w.enabled)


# -- DropDown upward ---------------------------------------------------------------------


class TestDropDownFlip(TextInputCase):
    def open(self, top_left, n=6):
        d = self.track(DropDown(top_left=top_left, width=200,
                                options=[f"o{i}" for i in range(n)]))
        self.click(d)
        self.assertTrue(d._is_open)
        return d

    def test_near_bottom_opens_up(self):
        d = self.open((20, 60))
        bottom, top = d._list_span()
        self.assertTrue(d._opens_up())
        self.assertGreaterEqual(bottom, d._y2)
        # Hit test, row lookup and drawn span agree: first row is at the top.
        x = (d._x1 + d._x2) / 2
        first_y = top - d._list_padding - d._option_height / 2
        last_y = bottom + d._list_padding + d._option_height / 2
        self.assertTrue(d.contains_point(x, first_y))
        self.assertEqual(d._option_index_at(x, first_y), 0)
        self.assertEqual(d._option_index_at(x, last_y), 5)
        self.assertFalse(d.contains_point(x, d._y1 - 20))
        self.wm.handle_mouse_down(x, last_y, self.btn)
        self.wm.handle_mouse_up(x, last_y, self.btn)
        self.assertEqual(d.value, "o5")
        d._is_open = True
        d._draw_priority(skia.Surface(1200, 800).getCanvas())

    def test_near_top_opens_down(self):
        d = self.open((20, 560))
        bottom, top = d._list_span()
        self.assertFalse(d._opens_up())
        self.assertLessEqual(top, d._y1)


# -- which keys reach the game while a box has focus --------------------------------------


PRIMARY_KEY = glfw.KEY_LEFT_SUPER if sys.platform == "darwin" else glfw.KEY_LEFT_CONTROL
PRIMARY_NAME = "CMD" if sys.platform == "darwin" else "CTRL"


class TestKeyRouting(TextInputCase):
    """Through ``ScenaFramework._handle_key``: the path GLFW events take."""

    def setUp(self):
        super().setUp()
        from scena.orchestration import ScenaFramework
        self.fw = ScenaFramework.get_instance()
        self.keys = self.fw.keys
        cm = self.fw.canvas_manager
        self._saved = (cm.on_key_down, cm.on_key_up)
        self.downs, self.ups = [], []
        cm.on_key_down = lambda key: self.downs.append(str(key))
        cm.on_key_up = lambda key: self.ups.append(str(key))
        self.held = []

    def tearDown(self):
        for code in reversed(self.held):
            self.fw._handle_key(None, code, 0, glfw.RELEASE, 0)
        cm = self.fw.canvas_manager
        cm.on_key_down, cm.on_key_up = self._saved
        super().tearDown()

    def down(self, code, mods=0):
        self.fw._handle_key(None, code, 0, glfw.PRESS, mods)
        self.held.append(code)

    def up(self, code, mods=0):
        self.fw._handle_key(None, code, 0, glfw.RELEASE, mods)
        self.held.remove(code)

    def tap(self, code, mods=0):
        self.down(code, mods)
        self.up(code, mods)

    def test_typing_keys_stay_in_the_box(self):
        tb = self.box()
        tb.focus()
        self.down(glfw.KEY_W)
        self.assertFalse(self.keys("W"))
        self.assertEqual(self.downs, [])
        self.up(glfw.KEY_W)
        self.assertEqual(self.ups, [])      # the up goes where the down went
        for code in (glfw.KEY_SPACE, glfw.KEY_1, glfw.KEY_COMMA, glfw.KEY_UP, glfw.KEY_ESCAPE):
            tb.focus()
            self.down(code)
            self.assertEqual(self.downs, [], code)
            self.up(code)

    def test_shift_letter_stays_in_the_box(self):
        tb = self.box()
        tb.focus()
        self.down(glfw.KEY_LEFT_SHIFT, SHIFT)
        self.down(glfw.KEY_W, SHIFT)
        self.assertFalse(self.keys("W"))
        self.assertTrue(self.keys("SHIFT"))   # modifiers are held-down state

    def test_primary_s_reaches_the_game_after_a_commit(self):
        # Rule: what the box shows is what a shortcut reads. Passing the key
        # with the text still pending was tried and rejected (stale saves).
        c = self.cell(10)
        seen = []
        tb = self.box(c, on_submit=seen.append)
        tb.focus()
        self.type("250")
        self.down(PRIMARY_KEY, PRIMARY)
        self.assertEqual(c.value, 10)         # a modifier alone does not commit
        self.down(glfw.KEY_S, PRIMARY)
        self.assertEqual(c.value, 250)        # committed before the game sees S
        self.assertTrue(self.keys(f"{PRIMARY_NAME}+S"))
        # Scena's chord rule: on_key gets the modifier, a modified play key
        # is a keyp chord only.
        self.assertEqual(self.downs, [PRIMARY_NAME])
        self.assertTrue(tb.focused)           # focus stays
        self.assertEqual(seen, [])            # not Enter: no on_submit
        self.up(glfw.KEY_S, PRIMARY)
        self.assertIn("S", self.ups)
        self.wm.set_focus(None)
        self.assertEqual(c.value, 250)

    def test_function_key_applies_the_text_too(self):
        c = self.cell("a")
        seen = []
        tb = self.box(c, on_submit=seen.append)
        tb.focus()
        self.type("b")
        self.down(glfw.KEY_F5)
        self.assertTrue(self.keys("F5"))
        self.assertEqual(c.value, "b")
        self.assertTrue(tb.focused)
        self.assertEqual(seen, [])
        self.type("c")                        # keeps editing after the commit
        self.press("ENTER")
        self.assertEqual(c.value, "bc")
        self.assertEqual(seen, ["bc"])

    def test_invalid_text_still_lets_the_key_through(self):
        c = self.cell(10)
        tb = self.box(c)
        tb.focus()
        self.type("x")
        self.down(glfw.KEY_S, PRIMARY)
        self.assertTrue(self.keys("S"))
        self.assertFalse(tb.is_valid)
        self.assertEqual(c.value, 10)

    def test_box_shortcuts_stay_in_the_box(self):
        tb = self.box(initial="hello")
        tb.focus()
        for code in (glfw.KEY_C, glfw.KEY_X, glfw.KEY_A, glfw.KEY_V):
            self.tap(code, PRIMARY)
        self.assertEqual(self.downs, [])
        self.assertEqual(uiw._clipboard_buffer, "hello")

    def test_undo_is_claimed_and_does_nothing(self):
        c = self.cell("abc")
        tb = self.box(c)
        tb.focus()
        self.press("END")
        self.type("d")
        for code, mods in ((glfw.KEY_Z, PRIMARY), (glfw.KEY_Z, PRIMARY | SHIFT),
                           (glfw.KEY_Y, PRIMARY)):
            self.down(code, mods)
            self.assertFalse(self.keys("Z") or self.keys("Y"))
            self.up(code, mods)
        self.assertEqual(self.downs, [])
        self.assertEqual(tb.text, "abcd")
        self.assertEqual(c.value, "abc")      # no commit either

    def test_function_and_page_keys_reach_the_game(self):
        tb = self.box()
        tb.focus()
        for code, name in ((glfw.KEY_F5, "F5"), (glfw.KEY_PAGE_UP, "PAGEUP"),
                           (glfw.KEY_INSERT, "INS")):
            self.down(code)
            self.assertTrue(self.keys(name), name)
            self.up(code)
        self.assertEqual(self.downs, ["F5", "PAGEUP", "INS"])
        self.assertTrue(tb.focused)

    def test_nothing_focused_everything_reaches_the_game(self):
        self.box()
        self.down(glfw.KEY_W)
        self.assertTrue(self.keys("W"))
        self.assertEqual(self.downs, ["W"])

    def test_windows_altgr_types_text(self):
        from unittest import mock
        with mock.patch.object(uiw, "_IS_MAC", False), mock.patch.object(uiw.sys, "platform", "win32"):
            tb = self.box()
            altgr = glfw.MOD_CONTROL | glfw.MOD_ALT
            self.assertTrue(tb._claims_key("Q", altgr))       # AltGr+Q types "@"
            self.assertFalse(uiw._edit_mods(altgr)[1])       # and is not Ctrl+V paste
            self.assertFalse(tb._claims_key("S", glfw.MOD_CONTROL))
        with mock.patch.object(uiw, "_IS_MAC", False), mock.patch.object(uiw.sys, "platform", "linux"):
            self.assertFalse(tb._claims_key("S", glfw.MOD_CONTROL | glfw.MOD_ALT))

    def test_macos_option_letter_types_text(self):
        from unittest import mock
        with mock.patch.object(uiw, "_IS_MAC", True):
            tb = self.box()
            self.assertTrue(tb._claims_key("O", glfw.MOD_ALT))     # Option+O types "ø"
            self.assertTrue(tb._claims_key("O", glfw.MOD_CONTROL))  # Ctrl is not Primary on macOS
            self.assertFalse(tb._claims_key("S", glfw.MOD_SUPER))


if __name__ == "__main__":
    unittest.main()
