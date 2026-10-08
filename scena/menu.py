"""Game menu: one question, shown until the player picks or it is destroyed.

Mouse only. ``modal=True`` (the default) dims the game and masks ``keyp`` /
``mouse.press``. A second modal menu raises. A new non-modal menu replaces
the open one. ``await menu`` returns the choice, or ``None`` if it closed
without one.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import skia

from .color import Color
from .process import Handle
from .shapes import Point, get_xy
from .state import Attribute, _init_composite
from .style import Gradient, Texture, _coerce_panel_material, _material_paint_for_rect
from .uiwidget import (
    UIWidget,
    _make_ui_font,
    _require_bound,
    draw_string_upright,
    measure_text,
    resolve_typeface,
    text_baseline_centered,
    ui,
)
from .validate import expect_bool, expect_callable, required_positional_count

# Header band is this much lighter (HSL) than a dark panel, and fully opaque.
# A light panel is darkened by the same amount so the strip still separates.
_MENU_HEADER_LIFT = 0.14
_MENU_HEADER_LIGHT_LIMIT = 0.72


def _as_options(options) -> list:
    if options is None or isinstance(options, (str, bytes)) or not hasattr(options, "__iter__"):
        raise TypeError(
            f"Menu options= expected a list of choices, got "
            f"{type(options).__name__} {options!r}. "
            f"Write options=[\"Jogar\", \"Sair\"]."
        )
    options = list(options)
    if not options:
        raise ValueError(
            "Menu options= is empty; give at least one choice, "
            "e.g. options=[\"Jogar\", \"Sair\"]."
        )
    return options


_MENU_NO_ENABLED = (
    "Menu has no enabled: it is a question, not a control. Close it with "
    "destroy() (awaiters get None)."
)


class Menu(UIWidget):
    """Pop-up list of choices. Creating it shows it. Picking closes it.

    Args:
        cell: Data cell that receives the chosen option (``st.ship``).
        options: The choices (a list). The label is ``str(option)``; the chosen value is
            the item itself.
        on_choose: ``fn(option)`` called on every pick (not on ``destroy()``).
        title: Banner text on top; omit for options only.
        cols: 1 = vertical (default); ``len(options)`` = one row; another number = a
            grid.
        modal: Dim the game behind it; only one modal at a time (default ``True``).
        pause: Pause the clock while open; restored on close (default ``False``).
        center: Panel center on the screen (a point or a function; view space).
        box: Fill a Box instead (the font shrinks to fit, down to a legible minimum).
        font: Font family or file.
        font_size: Label size in design units.
        color: Label color (a color only).
        background: Panel paint: a color, ``Gradient`` or ``Texture``. A material
            fits the panel like a shape fill (the ramp ends at the rim).
        icons: One image file per option, shown above its label.
        group: Group tag(s).
    """

    # Class defaults so Entity.__setattr__ does not store these as ink.
    title = None
    modal = True

    def __init__(
        self,
        cell: Attribute | None = None,
        *,
        options=None,
        on_choose=None,
        title: str | None = None,
        cols: int = 1,
        modal: bool = True,
        pause: bool = False,
        center=None,
        box=None,
        font=None,
        font_size=None,
        color=None,
        background=None,
        icons=None,
        group=None,
    ):
        from .state import as_payload
        options = as_payload(options)
        title = as_payload(title)
        cols = as_payload(cols)
        modal = as_payload(modal)
        pause = as_payload(pause)
        font = as_payload(font)
        font_size = as_payload(font_size)
        color = as_payload(color)
        if isinstance(color, (Gradient, Texture)):
            raise TypeError(
                f"Menu color= is the label color and takes a color, got "
                f"{type(color).__name__}. For a {type(color).__name__} panel, "
                f"write background={type(color).__name__}(...)."
            )
        background = _coerce_panel_material(background, what="Menu background=")
        # center and box may be links or Boxes — do not unwrap callables.
        if callable(center) and not isinstance(center, type):
            center_value = center
        else:
            center_value = as_payload(center)
        box = box if box is not None else None

        options = _as_options(options)
        if not isinstance(cols, int) or isinstance(cols, bool) or cols < 1:
            raise TypeError(
                f"Menu cols= expected an int >= 1, got {cols!r}."
            )
        modal = expect_bool(modal, "Menu modal")
        pause = expect_bool(pause, "Menu pause")
        if center_value is not None and box is not None:
            raise TypeError(
                "Menu takes center= or box=, not both."
            )
        if on_choose is not None:
            expect_callable(on_choose, what="Menu on_choose")
            needed = required_positional_count(on_choose)
            if needed is not None and needed > 1:
                raise TypeError(
                    "on_choose receives the chosen option: "
                    "write def escolher(opcao):"
                )
        _require_bound(cell, "Menu")
        if icons is not None:
            icons = list(icons)
            if len(icons) != len(options):
                raise ValueError(
                    f"Menu icons= has {len(icons)} image(s) for {len(options)} "
                    f"option(s). Give one icon per option."
                )

        from .orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        wm = fw.widget_manager
        if modal:
            current = getattr(wm, "_open_modal_menu", None)
            if current is not None and getattr(current, "is_alive", False):
                label = getattr(current, "title", None) or "menu"
                raise RuntimeError(
                    f"A menu is already open ({label!r}). "
                    f"Close it before opening another."
                )

        super().__init__(group=group, stack=False)
        self.options = options
        self._labels = [str(item) for item in options]
        self._on_choose = on_choose
        self._on_choose_arity = 0 if on_choose is None else (
            required_positional_count(on_choose) or 0
        )
        self.title = None if title is None else str(title)
        self._cols = cols
        self.modal = modal
        self._pause = pause
        self._font_spec = None if font is None or font == "" else str(font)
        self._font_size = None if font_size is None else float(font_size)
        self._color = None if color is None else Color(color)
        self._background = background
        self._icons = icons
        self._icon_images = self._load_icons(icons) if icons else None
        self._icon_side = 0.0
        self._box = box
        self._uses_center = center_value is not None
        self._settled = False
        self._result_value = None
        self._hover_index = -1
        self._fit_warned = False
        self._clock_was_paused = None
        self._apply_data(cell, None, default=None)

        if self._uses_center:
            _init_composite(self.center, center_value)

        self._choice_handle = Handle._make(
            kind="menu",
            owner=self,
            must_await=False,
        )
        self._layout()
        if self._pause:
            self._clock_was_paused = bool(fw.clock.paused)
            fw.clock.paused = True
        wm.note_menu_opened(self)

    @property
    def enabled(self):
        """Refused: a Menu is a question, not a control. Close it with ``destroy()``."""
        raise AttributeError(_MENU_NO_ENABLED)

    @enabled.setter
    def enabled(self, value) -> None:
        # A disabled modal Menu would block every input with nothing to click.
        raise AttributeError(_MENU_NO_ENABLED)

    @property
    def choice(self):
        """Last result given to ``await``: the option, or ``None`` if closed without one."""
        return self._result_value

    @choice.setter
    def choice(self, value) -> None:
        raise AttributeError("Menu.choice is read-only. The player picks an option.")

    def _complete_handle(self, value) -> None:
        self._result_value = value
        handle = self._choice_handle
        if handle is None or handle._done or handle._cancelled:
            return
        handle._result = value
        handle._mark_complete()

    def _close_chrome(self) -> None:
        wm = self._widget_manager
        if wm is not None:
            wm.note_menu_closed(self)
        if self._pause:
            from .orchestration import ScenaFramework
            clock = ScenaFramework.get_instance().clock
            clock.paused = bool(self._clock_was_paused)
            self._pause = False

    def _choose(self, value) -> None:
        if self._settled:
            return
        self._settled = True
        self._close_chrome()
        if not self._data_is_linked():
            self.data = value
        self._complete_handle(value)
        callback = self._on_choose
        arity = self._on_choose_arity
        super().destroy()
        if callback is not None:
            if arity <= 0:
                callback()
            else:
                callback(value)

    def destroy(self):
        """Close the menu now. An ``await menu`` gets ``None`` (no choice). Safe to call twice."""
        if not getattr(self, "_settled", False):
            self._settled = True
            self._close_chrome()
            self._complete_handle(None)
        if not self.is_alive:
            return self
        return super().destroy()

    def __await__(self):
        handle = self._choice_handle
        handle._awaited = True
        try:
            while not handle._done and not handle._cancelled:
                yield handle
            if handle._cancelled:
                return None
            return handle._result
        finally:
            if self.is_alive:
                self.destroy()

    def _load_icons(self, icons) -> list:
        from .style import _load_image
        images = []
        for name in icons:
            if not isinstance(name, str) or not name.strip():
                raise TypeError(
                    f"Menu icons= expected image file names, got {name!r}. "
                    f"Write icons=[\"azul.png\", \"vermelha.png\"]."
                )
            images.append(_load_image(name, kind="menu icon"))
        return images

    def _draw_card(self, canvas):
        """The panel paints itself. No chrome card under the backdrop."""
        return

    def _view_size(self) -> tuple[float, float]:
        from .orchestration import ScenaFramework
        fw = ScenaFramework.get_instance()
        return float(fw.design_width), float(fw.design_height)

    def _typeface(self):
        spec = self._font_spec if self._font_spec else ui.font
        return resolve_typeface(spec)

    def _layout(self) -> None:
        theme = self._theme
        theme._ensure()
        vw, vh = self._view_size()
        pad = theme.menu_pad
        gap = theme.menu_gap
        option_size = self._font_size if self._font_size is not None else theme.menu_font_size
        ratio = theme.menu_title_size / theme.menu_font_size if theme.menu_font_size else 1.25
        title_size = option_size * ratio
        typeface = self._typeface()
        cols = self._cols
        n = len(self.options)
        rows = int(math.ceil(n / cols))
        self._rows = rows

        if self._box is not None:
            cx, cy = get_xy(self._box.center, bare=True)
            bw = float(self._box.width)
            bh = float(self._box.height)
            self._fit_into(bw, bh, option_size, title_size, typeface, cols, rows, pad, gap)
            self._x1 = cx - bw * 0.5
            self._y1 = cy - bh * 0.5
            self._x2 = self._x1 + bw
            self._y2 = self._y1 + bh
        else:
            self._option_size = option_size
            self._title_size = title_size
            self._build_metrics(typeface, cols, rows, pad, gap)
            if self._uses_center:
                cx = float(self.center.x)
                cy = float(self.center.y)
            else:
                cx, cy = vw * 0.5, vh * 0.5
            self._x1 = cx - self.width * 0.5
            self._y1 = cy - self.height * 0.5
            self._x2 = self._x1 + self.width
            self._y2 = self._y1 + self.height
        self._clamp(vw, vh)
        self.width = self._x2 - self._x1
        self.height = self._y2 - self._y1

    def _fit_into(self, bw, bh, option_size, title_size, typeface, cols, rows, pad, gap) -> None:
        theme = self._theme
        floor = theme.menu_min_font_size
        size = option_size
        while True:
            self._option_size = size
            self._title_size = title_size * (size / option_size) if option_size else size
            self._build_metrics(typeface, cols, rows, pad, gap)
            if self.width <= bw + 0.5 and self.height <= bh + 0.5:
                break
            if size <= floor + 0.01:
                if not self._fit_warned:
                    self._fit_warned = True
                    from .process import report_author_warning
                    report_author_warning(
                        "Menu",
                        "text does not fit the box at the smallest readable size; clipping.",
                    )
                break
            size = max(floor, size - 1.0)
        # Panel is the box; cells use the fitted metrics but stay inside it.
        self.width = bw
        self.height = bh

    def _build_metrics(self, typeface, cols, rows, pad, gap) -> None:
        opt_font = _make_ui_font(typeface, self._option_size)
        title_font = _make_ui_font(typeface, self._title_size)
        self._option_font = opt_font
        self._title_font = title_font
        widest = 0.0
        for label in self._labels:
            widest = max(widest, measure_text(opt_font, label))
        line = max(self._option_size * 1.4, 8.0)
        icon_side = self._option_size * 2.2 if self._icon_images else 0.0
        self._icon_side = icon_side
        cell_w = max(widest, icon_side) + pad
        cell_h = line + gap + (icon_side + gap if icon_side else 0.0)
        self._cell_w = cell_w
        self._cell_h = cell_h
        grid_w = cols * cell_w
        grid_h = rows * cell_h
        title_h = 0.0
        title_w = 0.0
        option_pad = self._theme.menu_option_pad
        if self.title:
            title_w = measure_text(title_font, self.title)
            title_h = max(self._title_size * 1.4, 8.0)
        self._title_h = title_h
        self._title_gap = option_pad if self.title else 0.0
        self.width = max(grid_w, title_w) + pad * 2
        # Header keeps menu_pad above the title. The option block uses
        # menu_option_pad above and below.
        chrome = (pad + title_h) if self.title else 0.0
        self.height = chrome + grid_h + option_pad * 2
        self._grid_w = grid_w
        self._grid_h = grid_h

    def _clamp(self, vw: float, vh: float) -> None:
        dx = 0.0
        dy = 0.0
        if self._x1 < 0:
            dx = -self._x1
        elif self._x2 > vw:
            dx = vw - self._x2
        if self._y1 < 0:
            dy = -self._y1
        elif self._y2 > vh:
            dy = vh - self._y2
        self._x1 += dx
        self._x2 += dx
        self._y1 += dy
        self._y2 += dy

    def _option_well(self) -> tuple[float, float]:
        """Y-up (bottom, top) of the area the option grid is centered in.

        With a title, that area is everything under the header band. Without
        one, it is the whole panel.
        """
        if self.title:
            return self._y1, self._header_band_rect().y()
        return self._y1, self._y2

    def _grid_origin(self) -> tuple[float, float]:
        """Lower-left of the option grid (y-up), centered in the option well."""
        grid_x = self._x1 + (self.width - self._grid_w) * 0.5
        bottom, top = self._option_well()
        grid_y = bottom + (top - bottom - self._grid_h) * 0.5
        return grid_x, grid_y

    def _title_baseline(self) -> float:
        """Baseline that centers the title's ink in the header band.

        Uses the string's tight glyph box. The font ascent is taller than the
        visible letters, so centering that box sits the title low in the band.
        """
        band = self._header_band_rect()
        center = band.y() + band.height() * 0.5
        bounds = skia.Rect()
        self._title_font.measureText(self.title, bounds=bounds)
        if bounds.isEmpty():
            return text_baseline_centered(band.y(), band.height(), self._title_font)
        # Skia bounds are y-down around the baseline (top < 0, bottom > 0).
        return center + (bounds.fTop + bounds.fBottom) * 0.5

    def _option_index_at(self, x: float, y: float) -> int:
        grid_x, grid_y = self._grid_origin()
        if x < grid_x or y < grid_y:
            return -1
        col = int((x - grid_x) / self._cell_w) if self._cell_w else -1
        row_from_bottom = int((y - grid_y) / self._cell_h) if self._cell_h else -1
        row = self._rows - 1 - row_from_bottom
        if col < 0 or row < 0 or col >= self._cols or row >= self._rows:
            return -1
        idx = row * self._cols + col
        if idx < 0 or idx >= len(self.options):
            return -1
        return idx

    def _sync_anchor(self) -> None:
        if self._uses_center or self._box is not None:
            self._layout()

    def _on_mouse_move(self, x, y):
        self._sync_anchor()
        self._hover_index = self._option_index_at(x, y)
        return True

    def _on_mouse_leave(self, x, y):
        self._hover_index = -1

    def _on_mouse_click(self, x, y, button):
        from .input import Mouse
        if button != Mouse.BTN_LEFT:
            return False
        self._sync_anchor()
        idx = self._option_index_at(x, y)
        if idx < 0:
            return True
        self._choose(self.options[idx])
        return True

    def _highlight_paint(self):
        """Highlight from the author's ink or the panel's tone; otherwise the theme.

        A Gradient panel uses ``mean_color()``; a Texture its proxy ``color``.
        """
        theme = self._theme
        base = self._color
        bg = self._background
        if base is None:
            if isinstance(bg, Gradient):
                base = bg.mean_color()
            elif isinstance(bg, Texture):
                base = bg.color
            elif bg is not None:
                base = bg
        if base is None:
            return theme.menu_highlight_bkg
        hi = base.lighter(0.45).with_alpha(0.5)
        paint = skia.Paint(AntiAlias=True)
        paint.setColor4f(hi.color4f)
        return paint

    def _paint_for(self, theme_paint, color: Color | None):
        if color is None:
            return theme_paint
        paint = skia.Paint(AntiAlias=True)
        paint.setColor4f(color.color4f)
        return paint

    def _header_from(self, base: Color):
        light = base.hsl[2]
        if light >= _MENU_HEADER_LIGHT_LIMIT:
            shifted = base.darker(_MENU_HEADER_LIFT)
        else:
            shifted = base.lighter(_MENU_HEADER_LIFT)
        paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
        paint.setColor4f(shifted.with_alpha(1.0).color4f)
        return paint

    def _header_paint(self):
        """Lighter opaque strip. A material panel gets a light veil instead."""
        bg = self._background
        if isinstance(bg, (Gradient, Texture)):
            return self._theme.menu_header_veil
        if bg is not None:
            return self._header_from(bg)
        return self._header_from(self._theme.menu_panel_color)

    def _header_band_rect(self):
        """Y-up rect of the title strip (top pad + title line), or None."""
        if not self.title:
            return None
        band_h = self._theme.menu_pad + self._title_h
        return skia.Rect.MakeXYWH(self._x1, self._y2 - band_h, self.width, band_h)

    def _panel_paint(self):
        """Panel fill. A material is fitted and anchored to the panel rect."""
        bg = self._background
        if isinstance(bg, (Gradient, Texture)):
            hw = self.width * 0.5
            hh = self.height * 0.5
            return _material_paint_for_rect(bg, self._x1 + hw, self._y1 + hh, hw, hh)
        if bg is not None:
            return self._paint_for(self._theme.menu_panel_bkg, bg)
        return self._theme.menu_panel_bkg

    def draw(self, canvas):
        self._sync_anchor()
        theme = self._theme
        if self.modal:
            vw, vh = self._view_size()
            canvas.drawRect(skia.Rect.MakeXYWH(0, 0, vw, vh), theme.menu_backdrop)
        rect = skia.Rect.MakeXYWH(self._x1, self._y1, self.width, self.height)
        rrect = skia.RRect.MakeRectXY(rect, theme.corner_radius * 2, theme.corner_radius * 2)
        canvas.drawRRect(rrect, self._panel_paint())
        canvas.save()
        canvas.clipRRect(rrect, True)
        band = self._header_band_rect()
        if band is not None:
            canvas.drawRect(band, self._header_paint())
        if self._hover_index >= 0:
            grid_x, grid_y = self._grid_origin()
            row = self._hover_index // self._cols
            col = self._hover_index % self._cols
            row_from_bottom = self._rows - 1 - row
            hx = grid_x + col * self._cell_w
            hy = grid_y + row_from_bottom * self._cell_h
            hrect = skia.Rect.MakeXYWH(hx, hy, self._cell_w, self._cell_h)
            canvas.drawRRect(
                skia.RRect.MakeRectXY(hrect, theme.corner_radius, theme.corner_radius),
                self._highlight_paint(),
            )
        ink = self._paint_for(theme.menu_text, self._color)
        title_ink = self._paint_for(theme.menu_title_text, self._color)
        if self.title:
            tw = measure_text(self._title_font, self.title)
            tx = self._x1 + (self.width - tw) * 0.5
            draw_string_upright(
                canvas, self.title, tx, self._title_baseline(), self._title_font, title_ink,
            )
        grid_x, grid_y = self._grid_origin()
        for i, label in enumerate(self._labels):
            row = i // self._cols
            col = i % self._cols
            row_from_bottom = self._rows - 1 - row
            cx = grid_x + col * self._cell_w
            cy = grid_y + row_from_bottom * self._cell_h
            lw = measure_text(self._option_font, label)
            label_top = cy
            label_h = self._cell_h
            side = self._icon_side
            if side and self._icon_images is not None:
                img = self._icon_images[i]
                ix = cx + (self._cell_w - side) * 0.5
                iy = cy + self._cell_h - side
                src = skia.Rect.MakeWH(float(img.width()), float(img.height()))
                dst = skia.Rect.MakeXYWH(ix, iy, side, side)
                canvas.drawImageRect(img, src, dst, skia.SamplingOptions())
                label_h = self._cell_h - side
            draw_string_upright(
                canvas,
                label,
                cx + (self._cell_w - lw) * 0.5,
                text_baseline_centered(label_top, label_h, self._option_font),
                self._option_font,
                ink,
            )
        canvas.restore()

    def __repr__(self) -> str:
        label = self.title if getattr(self, "title", None) else "menu"
        return f"Menu({label!r})"


# ContainerSlot must be assigned on the class before instances. Done here so
# the import of Point above is finished.
from .state import ContainerSlot as _ContainerSlot  # noqa: E402

Menu.center = _ContainerSlot(Point)
