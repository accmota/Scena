"""
Unit tests for UIWidget bind, commit, layout, and input (headless).

Run:

    python -m unittest tests.test_uiwidget -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Color, Text, init, st, ui
from scena.input import Mouse
from scena.orchestration import ScenaFramework
from scena.state import Attribute, LinkedAttributeError
from scena.uiwidget import (
    Button, CheckBox, DropDown, Slider, TextInput,
    _UI_MIN_LABEL_SPACE, _make_ui_font, iter_font_runs, measure_text,
)


class WidgetTestCase(unittest.TestCase):
    _key_n = 0

    def setUp(self):
        init(width=800, height=600)
        ui.scale = 1.0
        ui.font = None
        ui.min_label_space = _UI_MIN_LABEL_SPACE
        self.wm = ScenaFramework.get_instance().widget_manager
        self.btn = Mouse.BTN_LEFT
        self._owned = []
        self._captions = []

    def tearDown(self):
        if self.wm.focused_widget in self._owned:
            self.wm.set_focus(None)
        for w in self._owned:
            try:
                w.destroy()
            except Exception:
                pass
        self._owned.clear()
        for caption in self._captions:
            try:
                caption.destroy()
            except Exception:
                pass
        self._captions.clear()
        ui.min_label_space = _UI_MIN_LABEL_SPACE
        ui.scale = 1.0
        ui.font = None
        ui.stack_reset()

    def track(self, widget):
        self._owned.append(widget)
        return widget

    def key(self, prefix="ui"):
        WidgetTestCase._key_n += 1
        return f"{prefix}_{WidgetTestCase._key_n}"

    def click(self, widget):
        x = (widget._x1 + widget._x2) * 0.5
        y = (widget._y1 + widget._y2) * 0.5
        self.assertTrue(self.wm.handle_mouse_down(x, y, self.btn))
        self.assertTrue(self.wm.handle_mouse_up(x, y, self.btn))
        return x, y


class TestSliderBind(WidgetTestCase):
    def test_bind_identity_and_minmax_inherit(self):
        name = self.key("radius")
        st.create(name, initial=70.0)
        s = self.track(Slider(
            getattr(st, name), label="R", top_left=(20, 100), width=300,
            min_value=20.0, max_value=160.0,
        ))
        attr = getattr(st, name)
        self.assertIs(s.data, attr)
        self.assertEqual(s.min_value, 20.0)
        self.assertEqual(s.max_value, 160.0)
        self.assertAlmostEqual(float(s.value), 70.0)

        s.data = 100.0
        self.assertAlmostEqual(float(attr.value), 100.0)

        setattr(st, name, 40.0)
        self.assertAlmostEqual(s.percentage, (40.0 - 20.0) / (160.0 - 20.0))

    def test_wheel_steps_and_clamps(self):
        s = self.track(Slider(
            top_left=(20, 80), width=300,
            min_value=0.0, max_value=100.0, initial=50.0,
        ))
        s._on_mouse_scroll(0, 1)
        self.assertAlmostEqual(float(s.value), 52.0)
        s.data = 100.0
        s._on_mouse_scroll(0, 1)
        self.assertAlmostEqual(float(s.value), 100.0)
        s.data = 0.0
        s._on_mouse_scroll(0, -1)
        self.assertAlmostEqual(float(s.value), 0.0)

    def test_out_of_range_cell_is_not_corrected(self):
        # Guia #ui-slider (PM1): the Slider never rewrites its cell on its own.
        # A value outside the range (or not an int with only_int) stays until
        # a drag or the wheel writes a new one, and that one is in range.
        name = self.key("count")
        st.create(name, initial=100)
        s = self.track(Slider(getattr(st, name), label="N", top_left=(20, 140),
                              width=300, min_value=1, max_value=80, only_int=True))
        self.assertEqual(getattr(st, name).value, 100)
        setattr(st, name, 2.5)
        self.assertEqual(getattr(st, name).value, 2.5)
        setattr(st, name, 100)
        s._on_mouse_scroll(0, 1)
        self.assertEqual(getattr(st, name).value, 80)

    def test_wheel_only_int(self):
        s = self.track(Slider(
            top_left=(20, 60), width=300,
            min_value=0, max_value=10, initial=5, only_int=True,
        ))
        s._on_mouse_scroll(0, 1)
        self.assertEqual(s.value, 6)

    def test_only_int_default_rounds_midpoint(self):
        s = self.track(Slider(
            top_left=(20, 60), width=300,
            min_value=1, max_value=6, only_int=True,
        ))
        self.assertEqual(s.value, 4)

    def test_drag_only_int_reaches_min_and_max(self):
        s = self.track(Slider(
            top_left=(20, 60), width=300,
            min_value=-10, max_value=10, initial=0, only_int=True,
        ))
        y = s._slider_y
        s._on_mouse_down(s._slider_x, y, self.btn)
        s._on_mouse_drag(s._slider_x + s._slider_length + 50, y)
        self.assertEqual(s.value, 10)
        s._on_mouse_drag(s._slider_x - 50, y)
        self.assertEqual(s.value, -10)

    def test_track_click_only_int_quantizes_to_max(self):
        s = self.track(Slider(
            top_left=(20, 60), width=300,
            min_value=-10, max_value=10, initial=0, only_int=True,
        ))
        end_x = s._slider_x + s._slider_length
        s._on_mouse_down(end_x, s._slider_y, self.btn)
        self.assertEqual(s.value, 10)


class TestSliderHandleHit(WidgetTestCase):
    def _disc_right(self, s: Slider):
        hx, hy = s._get_handle_pos()
        return hx + s._handle_radius * 0.9, hy

    def test_max_disc_is_inside_box_and_hoverable(self):
        s = self.track(Slider(
            label="radius", top_left=(16, 100), width=280,
            min_value=10.0, max_value=80.0, initial=80.0,
        ))
        hx, hy = s._get_handle_pos()
        self.assertLessEqual(hx + s._handle_radius, s._x2)
        x, y = self._disc_right(s)
        self.assertTrue(s.contains_point(x, y))
        self.assertIs(self.wm.get_widget_at(x, y), s)
        self.wm.handle_mouse_move(x, y)
        self.assertTrue(s._is_mouse_over_handle)

    def test_max_disc_drag_starts(self):
        s = self.track(Slider(
            label="amount", top_left=(16, 140), width=280,
            min_value=0.2, max_value=2.0, initial=2.0,
        ))
        x, y = self._disc_right(s)
        self.assertTrue(self.wm.handle_mouse_down(x, y, self.btn))
        self.assertTrue(s._dragging_handle)
        self.wm.handle_mouse_move(x - 40, y)
        self.assertLess(float(s.value), s.max_value)
        self.assertTrue(self.wm.handle_mouse_up(x - 40, y, self.btn))

    def test_relayout_keeps_max_disc_in_box(self):
        s = self.track(Slider(
            label="—", top_left=(16, 180), width=280,
            min_value=0.0, max_value=100.0, initial=100.0,
        ))
        s.label = "radius"
        s._update_track_layout(max(s._theme.default_font.measureText("radius") + 10, 72))
        hx, hy = s._get_handle_pos()
        self.assertLessEqual(hx + s._handle_radius, s._x2)
        x, y = hx + s._handle_radius * 0.9, hy
        self.assertTrue(s.contains_point(x, y))
        self.assertIs(self.wm.get_widget_at(x, y), s)

    def test_overflowing_disc_still_hits(self):
        s = self.track(Slider(
            label="radius", top_left=(16, 220), width=280,
            min_value=0.0, max_value=100.0, initial=100.0,
        ))
        # Old remap math omitted label_space from length, putting the disc past x2.
        s._label_space = 72
        s._slider_x = s._x1 + s._handle_radius + s._label_space
        s._slider_length = (
            s.width - s._value_space - (2 * s._internal_margin) - (2 * s._handle_radius)
        )
        hx, hy = s._get_handle_pos()
        self.assertGreater(hx - s._handle_radius, s._x2)
        self.assertTrue(s.contains_point(hx, hy))
        self.assertIs(self.wm.get_widget_at(hx, hy), s)
        self.wm.handle_mouse_move(hx, hy)
        self.assertTrue(s._is_mouse_over_handle)
        self.assertTrue(self.wm.handle_mouse_down(hx, hy, self.btn))
        self.assertTrue(s._dragging_handle)
        self.wm.handle_mouse_up(hx, hy, self.btn)


class TestDropDownIndex(WidgetTestCase):
    def test_external_write_updates_selected_index(self):
        name = self.key("color")
        st.create(name, initial="cyan")
        d = self.track(DropDown(
            getattr(st, name),
            options=["cyan", "magenta", "gold"],
            top_left=(20, 200), width=220,
        ))
        self.assertEqual(d.value, "cyan")
        self.assertEqual(d.selected_index, 0)
        setattr(st, name, "gold")
        self.assertEqual(d.value, "gold")
        self.assertEqual(d.selected_index, 2)

    def _button_center(self, d):
        return (d._x1 + d._x2) * 0.5, (d._y1 + d._y2) * 0.5

    def _option_center(self, d, index):
        x = (d._x1 + d._x2) * 0.5
        y = (
            d._y1
            - d._list_margin_top
            - d._list_padding
            - d._option_height * (index + 0.5)
        )
        return x, y

    def test_reopen_after_select_stays_open(self):
        d = self.track(DropDown(
            options=["a", "b", "c"], top_left=(20, 200), width=220,
        ))
        bx, by = self._button_center(d)
        self.wm.handle_mouse_down(bx, by, self.btn)
        self.wm.handle_mouse_up(bx, by, self.btn)
        self.assertTrue(d._is_open)

        ox, oy = self._option_center(d, 1)
        self.wm.handle_mouse_move(ox, oy)
        self.wm.handle_mouse_down(ox, oy, self.btn)
        self.wm.handle_mouse_up(ox, oy, self.btn)
        self.assertFalse(d._is_open)
        self.assertEqual(d.value, "b")

        # Reopen with no move — stale hover must not close on release.
        self.wm.handle_mouse_down(bx, by, self.btn)
        self.wm.handle_mouse_up(bx, by, self.btn)
        self.assertTrue(d._is_open)

    def test_press_drag_release_on_option_selects(self):
        d = self.track(DropDown(
            options=["a", "b", "c"], top_left=(20, 240), width=220,
        ))
        bx, by = self._button_center(d)
        ox, oy = self._option_center(d, 2)
        self.wm.handle_mouse_down(bx, by, self.btn)
        self.assertTrue(d._is_open)
        self.wm.handle_mouse_move(ox, oy)
        self.wm.handle_mouse_up(ox, oy, self.btn)
        self.assertFalse(d._is_open)
        self.assertEqual(d.value, "c")


class TestTextBoxCommit(WidgetTestCase):
    def test_commit_on_focus_lost_and_invalid_keeps_data(self):
        name = self.key("n")
        st.create(name, initial=10)
        tb = self.track(TextInput(getattr(st, name), top_left=(20, 140), width=200))
        attr = getattr(st, name)

        tb._on_focus_gained()
        tb.text = "20"
        tb._on_focus_lost()
        self.assertEqual(attr.value, 20)
        self.assertTrue(tb.is_valid)

        tb._on_focus_gained()
        tb.text = "nope"
        tb._on_focus_lost()
        self.assertFalse(tb.is_valid)
        self.assertEqual(attr.value, 20)


class TestCheckBox(WidgetTestCase):
    def test_checked_is_data_alias(self):
        name = self.key("on")
        st.create(name, initial=False)
        attr = getattr(st, name)
        c = self.track(CheckBox(attr, label="Show", top_left=(20, 40)))
        self.assertIs(c.checked, attr)
        c.checked = True
        self.assertTrue(bool(attr.value))
        c.checked @= Attribute(False)
        self.assertFalse(bool(c.value))

    def test_toggle_and_initial_overrides_bound(self):
        name = self.key("on")
        st.create(name, initial=False)
        c = self.track(CheckBox(
            getattr(st, name), label="Show", top_left=(20, 40), initial=True,
        ))
        self.assertTrue(bool(getattr(st, name).value))
        c._on_mouse_click(c._x1 + 1, c._y1 + 1, self.btn)
        self.assertFalse(bool(getattr(st, name).value))


class TestButton(WidgetTestCase):
    def test_on_click_fires_on_release_not_down(self):
        clicks = []
        b = self.track(Button(
            label="Go", top_left=(20, 250), width=120,
            on_click=lambda: clicks.append(1),
        ))
        x = (b._x1 + b._x2) * 0.5
        y = (b._y1 + b._y2) * 0.5
        self.wm.handle_mouse_down(x, y, self.btn)
        self.assertEqual(clicks, [])
        self.wm.handle_mouse_up(x, y, self.btn)
        self.assertEqual(clicks, [1])

    def test_release_outside_cancels_the_click(self):
        # Guia #ui-button (PM1): on_click fires on release over the button only.
        clicks = []
        b = self.track(Button(
            label="Go", top_left=(20, 250), width=120,
            on_click=lambda: clicks.append(1),
        ))
        x = (b._x1 + b._x2) * 0.5
        y = (b._y1 + b._y2) * 0.5
        self.wm.handle_mouse_down(x, y, self.btn)
        self.wm.handle_mouse_up(b._x2 + 200, y, self.btn)
        self.assertEqual(clicks, [])

    def test_value_on_off_while_held(self):
        name = self.key("hold")
        st.create(name, initial=0.0)
        b = self.track(Button(
            getattr(st, name), label="H", top_left=(20, 300), width=120,
            value_on=2000.0, value_off=600.0,
        ))
        x = (b._x1 + b._x2) * 0.5
        y = (b._y1 + b._y2) * 0.5
        self.wm.handle_mouse_down(x, y, self.btn)
        self.assertAlmostEqual(float(getattr(st, name).value), 2000.0)
        self.wm.handle_mouse_up(x, y, self.btn)
        self.assertAlmostEqual(float(getattr(st, name).value), 600.0)


class TestLayoutAndEnabled(WidgetTestCase):
    def test_auto_layout_stacks_downward_y_up(self):
        ui.stack_reset()
        a = self.track(Button(label="AAAA"))
        b = self.track(Button(label="BBBB"))
        self.assertAlmostEqual(a._x1, b._x1)
        self.assertGreater(a._y1, b._y1)

    def test_visible_false_skips_hit(self):
        s = self.track(Slider(
            top_left=(20, 100), width=300,
            min_value=0.0, max_value=100.0, initial=50.0,
        ))
        x = (s._x1 + s._x2) * 0.5
        y = (s._y1 + s._y2) * 0.5
        self.assertIs(self.wm.get_widget_at(x, y), s)
        s.visible = False
        self.assertIsNone(self.wm.get_widget_at(x, y))

    def test_emptied_column_rewinds_to_the_same_slot(self):
        ui.stack_reset()
        ys = []
        x1 = None
        for _ in range(3):
            slider = Slider(label="Vol")
            ys.append(slider._y1)
            x1 = slider._x1
            slider.destroy()
        self.assertAlmostEqual(ys[0], ys[1])
        self.assertAlmostEqual(ys[1], ys[2])
        again = self.track(Slider(label="Vol"))
        self.assertAlmostEqual(again._y1, ys[0])
        self.assertAlmostEqual(again._x1, x1)

    def test_partial_destroy_does_not_rewind(self):
        ui.stack_reset()
        top = self.track(Button(label="A"))
        mid = self.track(Button(label="B"))
        top.destroy()
        nxt = self.track(Button(label="C"))
        self.assertLess(nxt._y1, mid._y1)

    def test_rewind_drops_pending_gap(self):
        ui.stack_reset()
        top = self.track(Button(label="A"))
        y = top._y1
        ui.gap()
        top.destroy()
        nxt = self.track(Button(label="B"))
        self.assertAlmostEqual(nxt._y1, y)

    def test_destroy_in_previous_column_does_not_move_cursor(self):
        ui.stack_reset()
        left = self.track(Button(label="A"))
        ui.stack_column()
        right = self.track(Button(label="B"))
        left.destroy()
        nxt = self.track(Button(label="C"))
        self.assertAlmostEqual(nxt._x1, right._x1)
        self.assertLess(nxt._y1, right._y1)


class TestBoxedCellFormatAndBrackets(WidgetTestCase):
    """Phase 5: State/widget cells stay boxed; format + bracket link protocol."""

    def test_state_format_spec(self):
        st.create("score", initial=12.5)
        self.assertEqual(f"{st.score:.1f}", "12.5")
        self.assertEqual(f"{st.score:05.1f}", "012.5")

    def test_slider_value_bracket_is_data_cell(self):
        s = self.track(Slider(
            top_left=(20, 80), width=200,
            min_value=0.0, max_value=100.0, initial=40.0,
        ))
        st.create("vol", initial=10.0)
        s["value"] @= lambda: st.vol * 2
        self.assertTrue(s["value"].is_linked)
        self.assertAlmostEqual(float(s.value), 20.0)
        st.vol = 15.0
        self.assertAlmostEqual(float(s.value), 30.0)
        s["value"].unlink()
        s.data = 50.0
        self.assertAlmostEqual(float(s.value), 50.0)

    def test_linked_checkbox_click_is_noop(self):
        st.create("flag", initial=False)
        c = self.track(CheckBox(label="Show", top_left=(20, 40)))
        c["checked"] @= st.flag
        self.assertFalse(bool(c.value))
        self.click(c)
        self.assertFalse(bool(c.value))
        st.flag = True
        self.assertTrue(bool(c.value))
        with self.assertRaises(LinkedAttributeError):
            c.checked = False

    def test_linked_slider_scroll_is_noop(self):
        s = self.track(Slider(
            top_left=(20, 80), width=200,
            min_value=0.0, max_value=100.0, initial=40.0,
        ))
        st.create("vol", initial=10.0)
        s["value"] @= lambda: st.vol * 2
        s._on_mouse_scroll(0, 1)
        self.assertAlmostEqual(float(s.value), 20.0)

    def test_linked_textbox_does_not_commit(self):
        st.create("title", initial="hero")
        tb = self.track(TextInput(top_left=(20, 40), width=200, initial="hi"))
        tb["data"] @= st.title
        self.assertEqual(tb.value, "hero")
        tb._on_focus_gained()
        tb.text = "nope"
        tb._on_focus_lost()
        self.assertEqual(tb.value, "hero")
        tb._on_char("x")
        self.assertEqual(tb.value, "hero")


class TestUiScaleAndFont(WidgetTestCase):
    def test_compact_defaults(self):
        theme = self.wm.widget_theme
        theme._ensure()
        self.assertAlmostEqual(ui.scale, 1.0)
        self.assertIsNone(ui.font)
        self.assertAlmostEqual(theme.font_size, 13.0)
        self.assertAlmostEqual(theme.row_height, 28.0)
        self.assertAlmostEqual(theme.default_width, 260.0)
        b = self.track(Button(label="Go", top_left=(20, 80)))
        self.assertAlmostEqual(b.width, 260.0)
        self.assertAlmostEqual(b.height, 28.0)

    def test_scale_multiplies_chrome_not_explicit_layout(self):
        ui.scale = 2.0
        b = self.track(Button(label="Go", top_left=(20, 80)))
        self.assertAlmostEqual(b.width, 520.0)
        self.assertAlmostEqual(b.height, 56.0)
        wide = self.track(Button(label="Go", top_left=(20, 20), width=300, height=40))
        self.assertAlmostEqual(wide.width, 300.0)
        self.assertAlmostEqual(wide.height, 40.0)

    def test_init_preserves_scale_and_font(self):
        ui.scale = 2.0
        ui.font = "Menlo"
        init(width=800, height=600)
        self.assertAlmostEqual(ui.scale, 2.0)
        self.assertEqual(ui.font, "Menlo")

    def test_init_kwargs_set_chrome(self):
        init(width=800, height=600, ui_scale=0.5, ui_font="Arial")
        self.assertAlmostEqual(ui.scale, 0.5)
        self.assertEqual(ui.font, "Arial")
        b = self.track(Button(label="Go", top_left=(20, 80)))
        self.assertAlmostEqual(b.width, 130.0)
        self.assertAlmostEqual(b.height, 14.0)

    def test_scale_must_be_positive(self):
        with self.assertRaises(ValueError):
            ui.scale = 0
        with self.assertRaises(ValueError):
            init(ui_scale=-1)

    def test_gap_is_a_column_verb(self):
        self.assertTrue(callable(ui.gap))
        ui.stack_reset()
        a = self.track(Button(label="A"))
        ui.gap()
        b = self.track(Button(label="B"))
        theme = self.wm.widget_theme
        theme._ensure()
        self.assertAlmostEqual(b._y2, a._y1 - 2 * theme.stack_gap, places=4)

    def test_arrows_use_a_real_glyph(self):
        self.wm.widget_theme._ensure()
        font = self.wm.widget_theme.default_font
        runs = list(iter_font_runs(font, "←/→"))
        self.assertTrue(runs)
        for run, run_font in runs:
            for ch in run:
                if ch in "←→":
                    self.assertGreater(run_font.unicharToGlyph(ord(ch)), 0, ch)

    def test_missing_glyph_falls_back(self):
        # Runs on every OS: a font file every OS installs (it used to need
        # Helvetica, so it only ran on the Mac), and the first character that
        # font lacks and some installed font has.
        import skia
        from tests.font_support import system_font_file
        path = system_font_file()
        if path is None:
            self.skipTest("no system monospace .ttf (tests/font_support.py)")
        base = skia.Typeface.MakeFromFile(path)
        font = _make_ui_font(base, 13)
        mgr = skia.FontMgr.RefDefault()
        missing = None
        for ch in "→★♫日한":
            if font.unicharToGlyph(ord(ch)):
                continue
            other = mgr.matchFamilyStyleCharacter(
                base.getFamilyName(), base.fontStyle(), ["en"], ord(ch))
            if other is not None and other.unicharToGlyph(ord(ch)):
                missing = ch
                break
        if missing is None:
            self.skipTest(f"{os.path.basename(path)} has every candidate, or no fallback font has it")
        runs = list(iter_font_runs(font, f"A{missing}B"))
        self.assertGreaterEqual(len(runs), 2)
        fallback = next(run_font for run, run_font in runs if missing in run)
        self.assertGreater(fallback.unicharToGlyph(ord(missing)), 0)


_LONG_LABEL = "A very long slider label for column alignment"


class TestMinLabelSpace(WidgetTestCase):
    def test_default_floor_on_short_label(self):
        s = self.track(Slider(
            label="R", top_left=(20, 100), width=300,
            min_value=0.0, max_value=1.0,
        ))
        self.assertAlmostEqual(ui.min_label_space, _UI_MIN_LABEL_SPACE)
        self.assertAlmostEqual(s._label_space, _UI_MIN_LABEL_SPACE)
        self.assertAlmostEqual(s._min_label_space, _UI_MIN_LABEL_SPACE)

    def test_author_floor_applies_to_next_slider_only(self):
        first = self.track(Slider(
            label="R", top_left=(20, 200), width=300,
            min_value=0.0, max_value=1.0,
        ))
        ui.min_label_space = 40.0
        second = self.track(Slider(
            label="G", top_left=(20, 160), width=300,
            min_value=0.0, max_value=1.0,
        ))
        self.assertAlmostEqual(first._label_space, _UI_MIN_LABEL_SPACE)
        self.assertAlmostEqual(second._label_space, 40.0)
        self.assertAlmostEqual(second._min_label_space, 40.0)

    def test_scale_multiplies_unscaled_floor(self):
        ui.scale = 2.0
        ui.min_label_space = 50.0
        s = self.track(Slider(
            label="R", top_left=(20, 100), width=520,
            min_value=0.0, max_value=1.0,
        ))
        self.assertAlmostEqual(s._min_label_space, 100.0)
        self.assertAlmostEqual(s._label_space, 100.0)

    def test_zero_means_natural_width(self):
        ui.min_label_space = 0.0
        s = self.track(Slider(
            label="R", top_left=(20, 100), width=300,
            min_value=0.0, max_value=1.0,
        ))
        natural = (
            measure_text(s._theme.default_font, "R")
            + 2 * s._theme.control_pad
        )
        self.assertAlmostEqual(s._label_space, natural)
        self.assertLess(s._label_space, _UI_MIN_LABEL_SPACE)

    def test_init_preserves_min_label_space(self):
        ui.min_label_space = 40.0
        init(width=800, height=600)
        self.assertAlmostEqual(ui.min_label_space, 40.0)

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            ui.min_label_space = -1
        self.assertAlmostEqual(ui.min_label_space, _UI_MIN_LABEL_SPACE)

    def test_relayout_keeps_construct_snapshot(self):
        s = self.track(Slider(
            label="R", top_left=(20, 100), width=300,
            min_value=0.0, max_value=1.0,
        ))
        ui.min_label_space = 40.0
        s._update_track_layout()
        self.assertAlmostEqual(s._label_space, _UI_MIN_LABEL_SPACE)


class TestLabelColumnAlign(WidgetTestCase):
    def _auto(self, label, **kwargs):
        return self.track(Slider(
            label=label, min_value=0.0, max_value=1.0, **kwargs,
        ))

    def _needed(self, slider):
        natural = (
            measure_text(slider._theme.default_font, str(slider.label))
            + 2 * slider._theme.control_pad
        )
        return max(natural, slider._min_label_space)

    def test_consecutive_auto_sliders_share_max_needed(self):
        ui.stack_reset()
        short = self._auto("R")
        long = self._auto(_LONG_LABEL)
        shared = self._needed(long)
        self.assertGreater(shared, _UI_MIN_LABEL_SPACE)
        self.assertAlmostEqual(short._label_space, shared)
        self.assertAlmostEqual(long._label_space, shared)
        self.assertAlmostEqual(short._slider_x, long._slider_x)

    def test_gap_starts_a_new_run(self):
        ui.stack_reset()
        a = self._auto("R")
        b = self._auto(_LONG_LABEL)
        ui.gap()
        c = self._auto("G")
        d = self._auto("B")
        self.assertAlmostEqual(a._label_space, self._needed(b))
        self.assertAlmostEqual(c._label_space, _UI_MIN_LABEL_SPACE)
        self.assertAlmostEqual(d._label_space, _UI_MIN_LABEL_SPACE)
        self.assertLess(c._label_space, a._label_space)

    def test_button_breaks_the_run(self):
        ui.stack_reset()
        a = self._auto("R")
        self.track(Button(label="Go"))
        b = self._auto(_LONG_LABEL)
        self.assertAlmostEqual(a._label_space, _UI_MIN_LABEL_SPACE)
        self.assertAlmostEqual(b._label_space, self._needed(b))

    def test_hud_text_breaks_the_run(self):
        ui.stack_reset()
        a = self._auto("R")
        caption = Text(text="section")
        self._captions.append(caption)
        b = self._auto(_LONG_LABEL)
        self.assertAlmostEqual(a._label_space, _UI_MIN_LABEL_SPACE)
        self.assertAlmostEqual(b._label_space, self._needed(b))

    def test_explicit_y1_does_not_join(self):
        ui.stack_reset()
        a = self._auto("R")
        b = self.track(Slider(
            label=_LONG_LABEL, top_left=(20, 80),
            min_value=0.0, max_value=1.0,
        ))
        self.assertAlmostEqual(a._label_space, _UI_MIN_LABEL_SPACE)
        self.assertAlmostEqual(b._label_space, self._needed(b))

    def test_unlabeled_does_not_join(self):
        ui.stack_reset()
        a = self._auto("R")
        bare = self.track(Slider(min_value=0.0, max_value=1.0))
        b = self._auto(_LONG_LABEL)
        self.assertAlmostEqual(a._label_space, _UI_MIN_LABEL_SPACE)
        self.assertEqual(bare._label_space, 0.0)
        self.assertAlmostEqual(b._label_space, self._needed(b))

    def test_explicit_top_left_is_not_in_the_run(self):
        # Only column slots share a label width; a placed Slider keeps its own
        # and ends the run (the next auto Slider starts a fresh one).
        ui.stack_reset()
        a = self._auto("R")
        b = self._auto(_LONG_LABEL, top_left=(80, 500))
        c = self._auto("S")
        self.assertAlmostEqual(a._label_space, _UI_MIN_LABEL_SPACE)
        self.assertAlmostEqual(b._label_space, self._needed(b))
        self.assertAlmostEqual(c._label_space, _UI_MIN_LABEL_SPACE)
        self.assertFalse(b._stack_auto)

    def test_stack_origin_starts_a_new_run(self):
        ui.stack_reset()
        a = self._auto("R")
        ui.stack_origin(40, 400)
        b = self._auto(_LONG_LABEL)
        self.assertAlmostEqual(a._label_space, _UI_MIN_LABEL_SPACE)
        self.assertAlmostEqual(b._label_space, self._needed(b))


class TestStackColumn(WidgetTestCase):
    def theme(self):
        self.wm.widget_theme._ensure()
        return self.wm.widget_theme

    def test_advances_x_and_returns_to_column_top(self):
        ui.stack_reset()
        a = self.track(Button(label="A"))
        b = self.track(Button(label="B"))
        ui.stack_column()
        c = self.track(Button(label="C"))
        gap = self.theme().stack_gap
        self.assertAlmostEqual(c._x1, a._x2 + gap, places=4)
        self.assertAlmostEqual(c._y2, a._y2, places=4)
        self.assertGreater(c._y1, b._y1)

    def test_uses_max_x2_not_last_item(self):
        ui.stack_reset()
        s = self.track(Slider(label="Vol"))
        t = Text("ok", font_size=16)
        self._captions.append(t)
        self.assertLess(t._x2, s._x2)
        ui.stack_column()
        c = self.track(Button(label="C"))
        self.assertAlmostEqual(c._x1, s._x2 + self.theme().stack_gap, places=4)
        self.assertAlmostEqual(c._y2, s._y2, places=4)

    def test_stack_origin_top_is_preserved(self):
        ui.stack_reset()
        ui.stack_origin(80, 300)
        a = self.track(Button(label="A"))
        self.track(Button(label="B"))
        ui.stack_column()
        c = self.track(Button(label="C"))
        self.assertAlmostEqual(a._y2, 300.0, places=4)
        self.assertAlmostEqual(c._y2, 300.0, places=4)
        self.assertAlmostEqual(c._x1, a._x2 + self.theme().stack_gap, places=4)

    def test_closes_label_column_run(self):
        ui.stack_reset()
        a = self.track(Slider(label="R", min_value=0.0, max_value=1.0))
        ui.stack_column()
        b = self.track(Slider(label=_LONG_LABEL, min_value=0.0, max_value=1.0))
        self.assertAlmostEqual(a._label_space, _UI_MIN_LABEL_SPACE)
        natural = (
            measure_text(b._theme.default_font, _LONG_LABEL)
            + 2 * b._theme.control_pad
        )
        self.assertAlmostEqual(b._label_space, max(natural, _UI_MIN_LABEL_SPACE))

    def test_pending_gap_does_not_inflate_column_gap(self):
        ui.stack_reset()
        a = self.track(Button(label="A"))
        ui.gap()
        ui.stack_column()
        b = self.track(Button(label="B"))
        self.assertAlmostEqual(b._x1, a._x2 + self.theme().stack_gap, places=4)
        self.assertAlmostEqual(b._y2, a._y2, places=4)

    def test_explicit_gap(self):
        ui.stack_reset()
        a = self.track(Button(label="A"))
        ui.stack_column(gap=24)
        b = self.track(Button(label="B"))
        self.assertAlmostEqual(b._x1, a._x2 + 24.0, places=4)
        self.assertAlmostEqual(b._y2, a._y2, places=4)

    def test_empty_double_call_skips_a_slot(self):
        ui.stack_reset()
        ui.stack_column()
        ui.stack_column()
        b = self.track(Button(label="B"))
        slot = self.theme().default_width + self.theme().stack_gap
        self.assertAlmostEqual(b._x1, 20.0 + 2 * slot, places=4)
        self.assertAlmostEqual(b._y2, 560.0, places=4)

    def test_stack_false_text_does_not_widen_column(self):
        ui.stack_reset()
        a = self.track(Button(label="A"))
        wide = Text(
            "this caption is intentionally much wider than a default button",
            top_left=(20, 16), font_size=14, stack=False,
        )
        self._captions.append(wide)
        self.assertGreater(wide._x2, a._x2)
        ui.stack_column()
        b = self.track(Button(label="B"))
        self.assertAlmostEqual(b._x1, a._x2 + self.theme().stack_gap, places=4)


class _ClickLogWidget:
    def __init__(self, log):
        self.log = log

    def _on_mouse_click(self, x, y, button):
        self.log.append("click")

    def _on_mouse_double_click(self, x, y, button):
        self.log.append("double")


class TestWidgetManagerDoubleClick(unittest.TestCase):
    """Double-click distance is Euclidean; a signed sum let up/left clicks through."""

    def setUp(self):
        from scena.orchestration import WidgetManager
        self.wm = WidgetManager()
        self.log = []
        self.w = _ClickLogWidget(self.log)

    def _clicks(self, *points, button=Mouse.BTN_LEFT):
        for x, y in points:
            self.wm.handle_mouse_click(x, y, button, self.w)

    def test_double_click_needs_same_button(self):
        self._clicks((200, 200))
        self._clicks((200, 200), button=Mouse.BTN_RIGHT)
        self.assertNotIn("double", self.log)

    def test_other_button_starts_new_pair(self):
        # LEFT, RIGHT, RIGHT → the two RIGHTs pair up.
        self._clicks((200, 200))
        self._clicks((200, 200), (200, 200), button=Mouse.BTN_RIGHT)
        self.assertEqual(self.log, ["click", "click", "click", "double"])

    def test_same_spot_is_double_click(self):
        self._clicks((200, 200), (200, 200))
        self.assertEqual(self.log, ["click", "click", "double"])

    def test_far_up_left_is_not_double_click(self):
        # Negative dx/dy: the old signed sum (-100) passed "< threshold".
        for second in [(100, 200), (200, 100), (100, 100), (300, 100)]:
            self.log.clear()
            self.wm.last_click = None
            self._clicks((200, 200), second)
            self.assertNotIn("double", self.log, second)

    def test_far_down_right_is_not_double_click(self):
        self._clicks((200, 200), (300, 200))
        self.assertNotIn("double", self.log)

    def test_distance_is_euclidean(self):
        t = self.wm.double_click_distance_threshold
        self._clicks((200, 200), (200 + t, 200))  # exactly on the threshold
        self.assertIn("double", self.log)
        self.log.clear()
        self._clicks((200, 200), (200 + t * 0.8, 200 + t * 0.8))  # |d| ≈ 1.13t
        self.assertNotIn("double", self.log)

    def test_press_timing_uses_perf_counter(self):
        import time
        self._clicks((200, 200))
        self.assertLess(abs(self.wm.last_click.time - time.perf_counter()), 1.0)


class TestWidgetTopLeft(WidgetTestCase):
    """Every widget is placed by one point: its visual top-left."""

    def _make_all(self, **kwargs):
        makers = {
            "Button": lambda kw: Button(label="B", **kw),
            "Slider": lambda kw: Slider(label="S", min_value=0.0, max_value=1.0, **kw),
            "CheckBox": lambda kw: CheckBox(label="C", **kw),
            "TextInput": lambda kw: TextInput(**kw),
            "DropDown": lambda kw: DropDown(options=["a", "b"], **kw),
        }
        return {name: self.track(make(dict(kwargs))) for name, make in makers.items()}

    def test_top_left_is_the_visual_top_left(self):
        for name, w in self._make_all(top_left=(120, 420)).items():
            with self.subTest(widget=name):
                self.assertAlmostEqual(w._x1, 120.0)
                self.assertAlmostEqual(w._y2, 420.0)
                self.assertLess(w._y1, 420.0)
                b = w.box
                self.assertAlmostEqual(float(b.top_left.x), 120.0)
                self.assertAlmostEqual(float(b.top_left.y), 420.0)

    def test_next_auto_item_stacks_below_a_placed_one(self):
        ui.stack_reset()
        placed = self.track(Button(label="placed", top_left=(300, 500)))
        nxt = self.track(Button(label="next"))
        self.assertAlmostEqual(nxt._x1, 300.0)
        self.assertAlmostEqual(
            nxt._y2, placed._y1 - self.wm.widget_theme.stack_gap, places=4,
        )

    def test_top_left_accepts_point_likes(self):
        from scena import Point, Vec2
        for value in ((10, 20), [10, 20], Point(10, 20), Vec2(10, 20)):
            with self.subTest(value=type(value).__name__):
                w = self.track(Button(label="p", top_left=value))
                self.assertEqual((w._x1, w._y2), (10.0, 20.0))

    def test_top_left_is_a_snapshot(self):
        for bad in (lambda: (1, 2), (lambda: 1, 2)):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError) as ctx:
                    Button(label="x", top_left=bad)
                self.assertIn("not a link", str(ctx.exception))

    def test_scalar_placement_keywords_orient_to_top_left(self):
        for cls, extra in ((Button, {}), (Slider, {}), (CheckBox, {}),
                           (TextInput, {}), (DropDown, {"options": ["a"]})):
            for kw in ("x1", "y1", "x", "pos"):
                with self.subTest(cls=cls.__name__, kw=kw):
                    with self.assertRaises(TypeError) as ctx:
                        cls(**extra, **{kw: 5})
                    msg = str(ctx.exception)
                    self.assertIn("top_left=(x, y)", msg)
                    self.assertNotIn("removed", msg)

    def test_box_is_a_read_only_snapshot(self):
        w = self.track(Button(label="b", top_left=(50, 300)))
        b = w.box
        self.assertAlmostEqual(float(b.width), w._x2 - w._x1)
        with self.assertRaises(AttributeError):
            w.box = b

    def test_stack_origin_takes_a_point(self):
        ui.stack_origin(200, 400)
        a = self.track(Button(label="a"))
        ui.stack_origin((200, 400))
        b = self.track(Button(label="b"))
        self.assertEqual((a._x1, a._y2), (b._x1, b._y2))
        s = self.track(Slider(label="s", min_value=0.0, max_value=1.0, top_left=(40, 500)))
        ui.stack_origin(s.box.top_right + (16, 0))
        c = self.track(Button(label="c"))
        self.assertAlmostEqual(c._x1, s._x2 + 16)
        self.assertAlmostEqual(c._y2, 500.0)
        with self.assertRaises(TypeError):
            ui.stack_origin("ab")
        with self.assertRaises(TypeError):
            ui.stack_origin(lambda: 1, 2)


class TestWheelRouting(WidgetTestCase):
    """Guia #reagir-callbacks (PM1): the widget under the pointer keeps the wheel
    (a Slider steps); a shape without wheel_rotate does not hold it; then
    on_mouse_scroll."""

    def _scroll_at(self, x, y):
        from unittest import mock
        import scena.orchestration as orch
        fw = ScenaFramework.get_instance()
        vs = fw.view_scale or 1.0
        sx = x * vs + fw._letterbox_pad_x
        sy = (fw.design_height - y) * vs + fw._letterbox_pad_y
        with mock.patch.object(orch.glfw, "get_cursor_pos", new=lambda _w: (sx, sy)):
            fw._handle_mouse_scroll(None, 0.0, 1.0)

    def test_slider_keeps_the_wheel_and_shapes_do_not(self):
        from scena import Rect
        fw = ScenaFramework.get_instance()
        cm = fw.canvas_manager
        seen = []
        saved = cm.on_mouse_scroll
        cm.on_mouse_scroll = lambda dx, dy: seen.append(dy)
        rect = Rect(center=(600, 300), width=80, height=40)
        try:
            s = self.track(Slider(top_left=(20, 500), width=300, min_value=0,
                                  max_value=10, initial=5, only_int=True))
            self._scroll_at((s._x1 + s._x2) / 2, (s._y1 + s._y2) / 2)
            self.assertEqual(s.value, 6)
            self.assertEqual(seen, [])
            self._scroll_at(600, 300)        # over a plain shape
            self.assertEqual(seen, [1.0])
        finally:
            cm.on_mouse_scroll = saved
            rect.destroy()



class TestDestroyedWidgetLeavesTheLastClick(WidgetTestCase):
    """HD4 (Testing Design, HD): the double-click memory must not keep a
    destroyed widget (a new widget at the same spot was a double click)."""

    def test_last_click_is_cleared_on_destroy(self):
        b = self.track(Button(label=self.key("hd")))
        self.click(b)
        self.assertIs(self.wm.last_click.widget, b)
        b.destroy()
        self.assertIsNone(self.wm.last_click)

    def test_a_button_that_destroys_itself_on_click_is_not_kept(self):
        # The click record used to be stored after the handler, so the clear
        # in remove_widget ran first and the dead button stayed (review S1-5).
        b = self.track(Button(label=self.key("hd2"), on_click=lambda: b.destroy()))
        self.click(b)
        self.assertFalse(b.is_alive)
        self.assertIsNone(self.wm.last_click)


if __name__ == "__main__":
    unittest.main(verbosity=2)
