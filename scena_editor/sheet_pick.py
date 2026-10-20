"""Choose a frame of a spritesheet: the canvas shows the sheet, the right
panel its cut.

The picker borrows the canvas: the sheet is drawn on its own world layer over
the level (an opaque backdrop hides the level; the overlay layer with the
selection's handles is hidden: Scena keeps ``top`` above every layer), with
the editor's camera — the
wheel zooms, a drag / Space+drag / the middle button pans, F fits. Scena does
not clip a layer to a region, so a box of its own would spill over the panels
when zoomed; the panels drawn over the world are the clip. A click without a
drag picks the frame under the pointer. The right panel shows the cut (the
``Sheet`` layouts: whole image, columns × rows, cell size, atlas), a name
filter for atlases and Cancel; the status bar names the frame under the
pointer, or the message ``Sheet`` gives for a cut it refuses. Every other
widget is disabled while the picker is up.

The cut is built through ``Sheet`` (``sheets.sheet_for``), so frames, names and
sizes are the game's.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from scena import Button, Color, DropDown, Line, Rect, Sprite, Text, TextInput, canvas

from . import _engine, sheets
from .i18n import t
from .toolbar import ACCENT, _safe
from .view import DESIGN, ITEM_LAYER, OVERLAY_LAYER, PANEL_RIGHT, PANEL_TOP, view_point

W, H = DESIGN
PICK_LAYER = "editor_pick"             # backdrop, the sheet, its outlines
MARK_LAYER = "editor_pick_marks"       # hover and current frame, over the outlines
MODES = ("whole", "grid", "cell", "atlas")
ATLAS_EXTS = (".xml", ".json")
BACKDROP = Color(0.15, 0.16, 0.18)
UNDER_IMAGE = Color(0.30, 0.31, 0.34)      # shows the sheet's bounds and its transparency
OUTLINE = Color(1, 1, 1, 0.35)
DIMMED = Color(0.08, 0.08, 0.1, 0.72)      # frames the filter leaves out
HOVER_FILL = Color(1, 1, 1, 0.22)       # reads on any art (accent on yellow did not)
DRAG_PX = 3.0
X0 = W - PANEL_RIGHT + 10
LABEL_W = 78.0
FIELD_W = PANEL_RIGHT - LABEL_W - 22
_CELL_IN_NAME = re.compile(r"\((\d+)\s*[x×X]\s*(\d+)\)")


# -- what the picker opens with ---------------------------------------------------------

def atlas_beside(png: str) -> Optional[str]:
    """An atlas with the image's stem next to it (``sheet.png`` → ``sheet.xml``)."""
    stem = os.path.splitext(png)[0]
    for ext in ATLAS_EXTS:
        if os.path.isfile(stem + ext):
            return stem + ext
    return None


def cell_in_name(png: str) -> Optional[Tuple[int, int]]:
    """``(16, 16)`` from a file named like ``Terrain (16x16).png``."""
    found = _CELL_IN_NAME.findall(os.path.basename(png))
    if not found:
        return None
    w, h = (int(v) for v in found[-1])
    return (w, h) if w > 0 and h > 0 else None


def image_for_atlas(atlas: str) -> Optional[str]:
    """The image an atlas goes with: the one it lists, else its stem as a PNG."""
    listed = _engine.atlas_image(atlas)
    if listed:
        return listed
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        path = os.path.splitext(atlas)[0] + ext
        if os.path.isfile(path):
            return path
    return None


def start_layout(png: str, entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The cut the picker shows first: the item's sheet; else an atlas beside
    the image; else a cell size in the file name; else the whole image."""
    if entry is not None:
        if entry.get("atlas"):
            return {"mode": "atlas", "atlas": entry["atlas"]}
        if entry.get("cell"):
            return {"mode": "cell", "cell": tuple(entry["cell"])}
        return {"mode": "grid", "cols": entry["cols"], "rows": entry.get("rows") or 1}
    atlas = atlas_beside(png)
    if atlas:
        return {"mode": "atlas", "atlas": atlas}
    cell = cell_in_name(png)
    if cell:
        return {"mode": "cell", "cell": cell}
    return {"mode": "whole"}


def entry_for(file: str, layout: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A sheet entry (absolute paths, no name) for a cut; None for the whole image."""
    mode = layout["mode"]
    if mode == "grid":
        rows = layout.get("rows") or 1
        return {"file": file, "cols": layout["cols"], "rows": rows if rows != 1 else None,
                "cell": None, "atlas": None}
    if mode == "cell":
        return {"file": file, "cols": None, "rows": None, "cell": tuple(layout["cell"]),
                "atlas": None}
    if mode == "atlas":
        return {"file": file, "cols": None, "rows": None, "cell": None, "atlas": layout["atlas"]}
    return None


def strip_guess(w: float, h: float) -> Dict[str, int]:
    """Columns × rows of square frames in a strip (``544 × 32`` → 17 × 1), else 1 × 1."""
    w, h = int(w), int(h)
    if h > 0 and w > h and w % h == 0:
        return {"cols": w // h, "rows": 1}
    if w > 0 and h > w and h % w == 0:
        return {"cols": 1, "rows": h // w}
    return {"cols": 1, "rows": 1}


def frame_at(frames: List[Tuple[tuple, tuple, str]], px: float, py: float) -> Optional[int]:
    """The frame whose packed rect holds image pixel ``(px, py)`` (y down); the
    smallest when rects overlap."""
    best, best_area = None, None
    for i, ((x, y, w, h), _size, _name) in enumerate(frames):
        if x <= px < x + w and y <= py < y + h:
            if best_area is None or w * h < best_area:
                best, best_area = i, w * h
    return best


# -- the picker -----------------------------------------------------------------------------

class FramePicker:
    """One open picker. ``on_pick(entry, frame, pixel_size)`` gets the cut (a
    sheet entry with absolute paths, or None for the whole image), the frame
    as the file writes it (index on a grid, name on an atlas; None for the
    whole image) and its untrimmed pixel size. ``on_close()`` runs either way."""

    def __init__(self, app, file: str, *, entry: Optional[Dict[str, Any]] = None,
                 layout: Optional[Dict[str, Any]] = None, current: Any = None,
                 on_pick: Callable, on_close: Callable[[], None]):
        self.app = app
        self.file = file
        self.current = current
        self.on_pick = on_pick
        self.on_close = on_close
        self.layout = dict(layout) if layout is not None else start_layout(file, entry)
        self.frames: List[Tuple[tuple, tuple, str]] = []
        self.error: Optional[str] = None
        self.hover: Optional[int] = None
        self.status = ""
        self._press: Optional[Tuple[float, float]] = None
        self._last_view: Optional[Tuple[float, float]] = None
        self._dragged = False
        self._zoom_seen = None
        self._outlines: List[Any] = []
        self._camera = (canvas.pan_x, canvas.pan_y, canvas.zoom)
        self._disabled = [w for w in _engine.live_widgets() if w.enabled]
        for w in self._disabled:
            w.enabled = False
        if PICK_LAYER not in canvas.layers:
            canvas.layers.create(PICK_LAYER, above=ITEM_LAYER)
            canvas.layers.create(MARK_LAYER, above=PICK_LAYER)
        self._overlay_was = canvas.layers[OVERLAY_LAYER].visible
        canvas.layers[OVERLAY_LAYER].visible = False
        self._build_world()
        self._build_panel()
        self._recut()
        self.fit()

    # -- building --------------------------------------------------------------------------
    def _build_world(self) -> None:
        self.backdrop = Rect(center=(0, 0), width=1, height=1, layer=PICK_LAYER)
        self.backdrop.fill = BACKDROP
        self.backdrop.line = None
        # The image at its pixel size: 1 pixel = 1 world unit, bottom-left at (0, 0).
        self.img_w, self.img_h = sheets.image_size(self.file)
        center = (self.img_w / 2, self.img_h / 2)
        self.under = Rect(center=center, width=self.img_w, height=self.img_h, layer=PICK_LAYER)
        self.under.fill = UNDER_IMAGE
        self.under.line = None
        self.sheet_image = Sprite(self.file, center=center, width=self.img_w,
                                  height=self.img_h, layer=PICK_LAYER)
        self.mark_current = Rect(center=(0, 0), width=1, height=1, layer=MARK_LAYER)
        self.mark_current.fill = None
        self.mark_current.line = ACCENT
        self.mark_current.visible = False
        self.mark_hover = Rect(center=(0, 0), width=1, height=1, layer=MARK_LAYER)
        self.mark_hover.fill = HOVER_FILL
        self.mark_hover.line = ACCENT
        self.mark_hover.visible = False

    def _build_panel(self) -> None:
        top = H - PANEL_TOP - 14
        self.texts: List[Text] = []
        self.widgets: List[Any] = []

        def text(s, y, size=13):
            obj = Text(s, top_left=(X0, y), font_size=size)
            self.texts.append(obj)
            return obj

        text(t("pick.title"), top, 15)
        from .panel import fit_text
        text(fit_text(os.path.basename(self.file), PANEL_RIGHT - 24, 12), top - 22, 12)
        y = top - 56
        text(t("pick.cut"), y + 4)
        self.mode_pick = DropDown(top_left=(X0 + LABEL_W, y + 8), width=FIELD_W, height=24,
                                  options=[t(f"pick.mode.{m}") for m in MODES],
                                  initial=t(f"pick.mode.{self.layout['mode']}"))
        self._mode_shown = self.mode_pick.data.value
        y -= 34
        self.label_a = text("", y + 4)
        self.input_a = TextInput(top_left=(X0 + LABEL_W, y + 8), width=FIELD_W, height=24,
                                 initial=1.0)
        y -= 30
        self.label_b = text("", y + 4)
        self.input_b = TextInput(top_left=(X0 + LABEL_W, y + 8), width=FIELD_W, height=24,
                                 initial=1.0)
        self.atlas_text = text("", y + 34 + 4, 12)
        self.atlas_button = Button(top_left=(X0, y + 8), width=PANEL_RIGHT - 20, height=24,
                                   label=t("pick.change_atlas"),
                                   on_click=_safe(self.choose_atlas, say=self.app.say))
        y -= 34
        self.label_filter = text(t("pick.filter"), y + 4)
        self.filter = TextInput(top_left=(X0 + LABEL_W, y + 8), width=FIELD_W, height=24,
                                initial="")
        self._filter_shown = ""
        y -= 34
        self.count_text = text("", y + 4, 12)
        y -= 34
        self.whole_button = Button(top_left=(X0, y + 8), width=PANEL_RIGHT - 20, height=28,
                                   label=t("pick.use_whole"),
                                   on_click=_safe(self.pick_whole, say=self.app.say))
        y -= 36
        self.cancel_button = Button(top_left=(X0, y + 8), width=PANEL_RIGHT - 20, height=28,
                                    label=t("pick.cancel"),
                                    on_click=_safe(self.cancel, say=self.app.say))
        self.widgets = [self.mode_pick, self.input_a, self.input_b, self.atlas_button,
                        self.filter, self.whole_button, self.cancel_button]
        self._fields_shown = (None, None)

    def _show_fields(self) -> None:
        mode = self.layout["mode"]
        grid, cell, atlas = mode == "grid", mode == "cell", mode == "atlas"
        for w, on in ((self.label_a, grid or cell), (self.input_a, grid or cell),
                      (self.label_b, grid or cell), (self.input_b, grid or cell),
                      (self.atlas_text, atlas), (self.atlas_button, atlas),
                      (self.label_filter, atlas), (self.filter, atlas),
                      (self.whole_button, mode == "whole")):
            if w.visible != on:
                if hasattr(w, "show"):
                    w.show(on)
                else:
                    w.visible = on
        if grid:
            self.label_a.text, self.label_b.text = t("pick.cols"), t("pick.rows")
            a, b = self.layout["cols"], self.layout.get("rows") or 1
        elif cell:
            self.label_a.text, self.label_b.text = t("pick.cell_w"), t("pick.cell_h")
            a, b = self.layout["cell"]
        else:
            a = b = None
        if a is not None:
            self.input_a.data.value = float(a)
            self.input_b.data.value = float(b)
        self._fields_shown = (self.input_a.data.value, self.input_b.data.value)
        if atlas:
            from .panel import fit_text
            self.atlas_text.text = fit_text(os.path.basename(self.layout["atlas"]),
                                            PANEL_RIGHT - 24, 12)

    # -- the cut -----------------------------------------------------------------------------
    def entry(self) -> Optional[Dict[str, Any]]:
        return entry_for(self.file, self.layout)

    def _recut(self) -> None:
        """Re-cut the sheet with the current layout and redraw the outlines."""
        self._show_fields()
        for g in self._outlines:
            g.destroy()
        self._outlines = []
        self.hover = None
        self.mark_hover.visible = False
        entry = self.entry()
        self.error = None
        self.frames = []
        if entry is not None:
            try:
                self.frames = sheets.frames(entry)
            except (ValueError, TypeError) as e:
                self.error = str(e)
        if self.layout["mode"] == "grid" or self.layout["mode"] == "cell":
            self._grid_lines()
        elif self.frames:
            for (x, y, w, h), _size, _name in self.frames:
                r = Rect(center=(x + w / 2, self.img_h - (y + h / 2)), width=w, height=h,
                         layer=PICK_LAYER)
                r.fill = None
                r.line = OUTLINE
                self._outlines.append(r)
        self._mark(self.mark_current, self._current_index())
        self._apply_filter(self.filter.data.value if self.layout["mode"] == "atlas" else "")
        self._zoom_seen = None
        n = len(self.frames)
        self.count_text.text = "" if self.error or entry is None else t("pick.count", count=n)

    def _grid_lines(self) -> None:
        if self.error or not self.frames:
            return
        (x0, y0, cw, ch), _s, _n = self.frames[0]
        cols = max(1, round(self.img_w / cw)) if cw else 1
        rows = max(1, round(self.img_h / ch)) if ch else 1
        for i in range(cols + 1):
            ln = Line(p1=(i * cw, 0), p2=(i * cw, self.img_h), layer=PICK_LAYER)
            ln.line = OUTLINE
            self._outlines.append(ln)
        for j in range(rows + 1):
            ln = Line(p1=(0, self.img_h - j * ch), p2=(self.img_w, self.img_h - j * ch),
                      layer=PICK_LAYER)
            ln.line = OUTLINE
            self._outlines.append(ln)

    def _current_index(self) -> Optional[int]:
        if self.current is None or not self.frames or self.error:
            return None
        try:
            return sheets.sheet_for(self.entry()).frame_index(self.current)
        except (ValueError, TypeError):
            return None

    def _mark(self, mark: Rect, index: Optional[int]) -> None:
        if index is None or index >= len(self.frames):
            mark.visible = False
            return
        (x, y, w, h), _s, _n = self.frames[index]
        mark.center = (x + w / 2, self.img_h - (y + h / 2))
        mark.width, mark.height = w, h
        mark.visible = True

    def _apply_filter(self, text: str) -> None:
        self._filter_shown = text
        if self.layout["mode"] != "atlas" or len(self._outlines) != len(self.frames):
            return
        needle = text.strip().casefold()
        for r, (_rect, _size, name) in zip(self._outlines, self.frames):
            r.fill = DIMMED if needle and needle not in name.casefold() else None

    # -- camera ------------------------------------------------------------------------------
    def fit(self) -> None:
        self.app.editor.viewport.fit((0.0, 0.0, float(self.img_w), float(self.img_h)))

    def _sync_camera(self) -> None:
        z = canvas.zoom
        key = (z, canvas.pan_x, canvas.pan_y)
        if key == self._zoom_seen:
            return
        self._zoom_seen = key
        self.backdrop.center = (canvas.pan_x, canvas.pan_y)
        self.backdrop.width = W * 1.2 / z
        self.backdrop.height = H * 1.2 / z
        width = 1.25 / z                   # screen pixels, at any zoom
        for g in self._outlines:
            g.line_width = width
        self.mark_hover.line_width = 2.0 / z
        self.mark_current.line_width = 2.5 / z

    # -- per frame ---------------------------------------------------------------------------
    def update(self) -> None:
        """Read the panel's controls; keep the backdrop and line widths with the camera."""
        chosen = self.mode_pick.data.value
        if chosen != self._mode_shown:
            self._mode_shown = chosen
            self._switch_mode(MODES[[t(f"pick.mode.{m}") for m in MODES].index(chosen)])
        values = (self.input_a.data.value, self.input_b.data.value)
        if values != self._fields_shown and self.layout["mode"] in ("grid", "cell"):
            self._fields_shown = values
            self._set_numbers(*values)
        if self.layout["mode"] == "atlas" and self.filter.data.value != self._filter_shown:
            self._apply_filter(self.filter.data.value)
        self._sync_camera()
        self.status = self._status_text()

    def _switch_mode(self, mode: str) -> None:
        if mode == "atlas":
            atlas = self.layout.get("atlas") or atlas_beside(self.file)
            if atlas is None:
                self.layout = {"mode": "atlas", "atlas": None}
                self.choose_atlas()
                return
            self.layout = {"mode": "atlas", "atlas": atlas}
        elif mode == "grid":
            self.layout = {"mode": "grid", **strip_guess(self.img_w, self.img_h)}
        elif mode == "cell":
            self.layout = {"mode": "cell", "cell": cell_in_name(self.file)
                           or (int(self.img_w), int(self.img_h))}
        else:
            self.layout = {"mode": "whole"}
        self._recut()

    def _set_numbers(self, a: Any, b: Any) -> None:
        def whole(v):
            try:
                n = float(v)
            except (TypeError, ValueError):
                return None
            return int(n) if n == int(n) and n >= 1 else None
        a, b = whole(a), whole(b)
        if a is None or b is None:
            self.error = t("pick.bad_number")
            return
        if self.layout["mode"] == "grid":
            self.layout = {"mode": "grid", "cols": a, "rows": b}
        else:
            self.layout = {"mode": "cell", "cell": (a, b)}
        self._recut()

    def _status_text(self) -> str:
        if self.error:
            return self.error
        if self.layout["mode"] == "whole":
            return t("pick.whole_size", w=f"{self.img_w:g}", h=f"{self.img_h:g}")
        if self.layout["mode"] == "atlas" and not self.layout.get("atlas"):
            return t("pick.no_atlas")
        index = self.hover if self.hover is not None else self._current_index()
        if index is None:
            return t("pick.hint")
        (_r, (w, h), name) = self.frames[index]
        label = name if self.layout["mode"] == "atlas" else str(index)
        return t("pick.frame", frame=label, w=f"{w:g}", h=f"{h:g}")

    # -- pointer (world coordinates, as the App gets them) ---------------------------------
    def pointer_down(self, x: float, y: float, button: int) -> None:
        self._press = view_point(x, y)
        self._last_view = self._press
        self._dragged = False

    def pointer_move(self, x: float, y: float) -> None:
        here = view_point(x, y)
        if self._press is not None:
            if not self._dragged and max(abs(here[0] - self._press[0]),
                                         abs(here[1] - self._press[1])) > DRAG_PX:
                self._dragged = True
            if self._dragged:
                z = canvas.zoom
                dx, dy = here[0] - self._last_view[0], here[1] - self._last_view[1]
                self.app.editor.viewport.pan_by(dx / z, dy / z)   # the sheet follows
            self._last_view = here
        self._hover_at(x, y)

    def pointer_up(self, x: float, y: float, button: int) -> None:
        pressed, self._press = self._press, None
        if pressed is None or self._dragged or button != 0:
            return
        index = self._index_at(x, y)
        if index is not None:
            self.pick(index)

    def _index_at(self, x: float, y: float) -> Optional[int]:
        if self.error or not self.frames or self.layout["mode"] == "whole":
            return None
        return frame_at(self.frames, x, self.img_h - y)

    def _hover_at(self, x: float, y: float) -> None:
        index = self._index_at(x, y)
        if index != self.hover:
            self.hover = index
            self._mark(self.mark_hover, index)

    def key(self, key: str) -> None:
        if key == "ESC":
            self.cancel()
        elif key == "F":
            self.fit()

    # -- results --------------------------------------------------------------------------
    def pick(self, index: int) -> None:
        entry = self.entry()
        frame = sheets.frame_key(entry, index)
        size = tuple(float(v) for v in self.frames[index][1])
        self.close()
        self.on_pick(entry, frame, size)

    def pick_whole(self) -> None:
        self.close()
        self.on_pick(None, None, (float(self.img_w), float(self.img_h)))

    def cancel(self) -> None:
        self.close()

    def choose_atlas(self) -> None:
        from . import dialogs
        start = os.path.dirname(self.file)

        def chosen(path):
            if path:
                self.layout = {"mode": "atlas", "atlas": os.path.abspath(path)}
            elif not self.layout.get("atlas"):
                self.layout = {"mode": "whole"}
                self.mode_pick.data.value = self._mode_shown = t("pick.mode.whole")
            self._recut()
        self.app.dialogs.start(lambda: dialogs.choose_atlas(start, t("dialog.atlas_title")),
                               chosen)

    def close(self) -> None:
        """Remove the picker, give the widgets back and restore the camera."""
        for g in [self.backdrop, self.under, self.sheet_image, self.mark_current,
                  self.mark_hover] + self._outlines + self.texts:
            g.destroy()
        for w in self.widgets:
            w.destroy()
        for w in self._disabled:
            if w.is_alive:
                w.enabled = True
        canvas.layers[OVERLAY_LAYER].visible = self._overlay_was
        px, py, z = self._camera
        canvas.zoom_to(z)
        canvas.pan_to(px, py)
        self.on_close()
