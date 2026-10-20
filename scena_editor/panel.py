"""Toolbar, top bar, properties panel and status bar (Scena widgets, view space).

Fields commit like every Scena ``TextInput``: on Enter or when focus moves.
``Panel.poll`` (every frame, before the canvas reacts) compares each field
with what it last showed and applies a change to the item the field was
showing — a click on the canvas commits the field in the same event that
changes the selection, so "the current selection" would be the wrong item.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from scena import Button, CheckBox, Color, DropDown, Slider, Text, TextInput

from . import _engine
from .i18n import t
from .geometry import union_aabb as geo_box
from .toolbar import BG, Tooltip, ToolButton, _rect, _safe, attach_tip
from .tools import (GRID_SIZES, KEY_OF, PRIMARY, REDO, Editor, _center, key_label,
                    partial_groups, rim_text, shared_groups)
from scena.level_format import SCOOPS
from .view import DESIGN, PANEL_BOTTOM, PANEL_LEFT, PANEL_RIGHT, PANEL_TOP

W, H = DESIGN
SEPARATOR = Color(1, 1, 1, 0.12)
# Left toolbar: what you create (shapes, a gap, then Image). Select and Pan
# live in the top bar, with Undo / Redo and the view controls.
CREATE_TOOLS = ("rect", "ellipse", "circle", "line", "polygon", "triangle", "regular_polygon",
                "track", "concave", "point", "image")
ROW = 30.0
X0 = W - PANEL_RIGHT + 10          # right panel content left edge
LABEL_W = 78.0
FILE_W = 78.0                      # New / Open / Save / Save as: one width
EDIT_W = 56.0                      # Undo / Redo
POINTER_W = 36.0                   # Select / Pan icon buttons (top bar)
GROUP_W = 170.0                    # the Select group dropdown (top bar)
TOOL_W, TOOL_H = 58.0, 44.0        # creation tool buttons (left toolbar)
TOOL_GAP = 12.0                    # extra space before the Image button
COORD_X = W - PANEL_RIGHT - 118    # the cursor readout starts here
FIELD_W = PANEL_RIGHT - LABEL_W - 22
NUMBER_W = 54.0                    # the number box beside a slider


def _keys_tip(name: str, keys: str) -> str:
    """"Save (Cmd+S)" — a button's name (no trailing …) and its shortcut."""
    return t("tip.keys", name=name.rstrip("…"), keys=key_label(keys))


def fit_text(text: str, width: float, size: float) -> str:
    """``text`` shortened in the middle (``arte/…/fundo.png``) to fit ``width``."""
    import skia
    font = skia.Font(skia.Typeface(""), size)
    if font.measureText(text) <= width:
        return text
    keep_end = max(len(text) // 2, 1)
    while keep_end > 1:
        for keep_start in range(len(text) - keep_end, -1, -1):
            candidate = text[:keep_start] + "…" + text[-keep_end:]
            if font.measureText(candidate) <= width:
                return candidate
        keep_end -= 1
    return "…" + text[-1:]


def _fit_end(text_obj: Text, text: str, right_limit: float) -> None:
    """Set ``text_obj`` to the longest ``text[:n] + "…"`` whose box ends before
    ``right_limit`` (measured on the Text itself, so the font is the real one)."""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        text_obj.text = text[:mid].rstrip() + "…"
        if text_obj.box.right <= right_limit:
            lo = mid
        else:
            hi = mid - 1
    text_obj.text = text[:lo].rstrip() + "…"


def _set_visible(element, visible: bool) -> None:
    """Show / hide a widget, Text, _Field or _Check only when it changes."""
    if element.visible != visible:
        if hasattr(element, "show"):
            element.show(visible)
        else:
            element.visible = visible


class _Field:
    """A labelled input in the properties panel."""

    def __init__(self, key: str, label: str, y: float, *, number: bool):
        self.key = key
        self.number = number
        self.label = Text(label, top_left=(X0, y - 4), font_size=13)
        self.input = TextInput(top_left=(X0 + LABEL_W, y), width=FIELD_W, height=24,
                               initial=0.0 if number else "")
        self.shown: Any = self.input.data.value
        self.owner: Any = None

    @property
    def visible(self) -> bool:
        return self.input.visible

    def show(self, visible: bool) -> None:
        self.label.visible = visible
        self.input.visible = visible

    def set(self, value: Any, owner: Any) -> None:
        value = round(float(value), 3) if self.number else str(value)
        self.owner = owner
        if self.input.data.value != value:
            self.input.data.value = value
        self.shown = value

    def committed(self) -> Optional[Any]:
        """The value the user committed since the last ``set``, else None."""
        if not self.input.visible:
            return None
        value = self.input.data.value
        if value == self.shown:
            return None
        self.shown = value
        return value


class _Slide(_Field):
    """A labelled slider with a number box beside it, for a bounded ratio
    tuned by eye (a track's Smooth, a triangle's Base ratio).

    Typing in the box commits like any ``_Field`` (``committed``). Dragging
    the slider previews: ``slid`` returns each new value (the panel applies
    it with no undo step) and ``dragging`` stays True until the handle is let
    go, when the panel records the drag as one step. ``lo`` / ``hi`` is the
    slider's range, inside what the level format accepts.
    """

    def __init__(self, key: str, label: str, y: float, lo: float, hi: float):
        self.key = key
        self.number = True
        self.label = Text(label, top_left=(X0, y - 4), font_size=13)
        slide_w = FIELD_W - NUMBER_W - 6
        self.slider = Slider(top_left=(X0 + LABEL_W, y + 2), width=slide_w, min_value=lo,
                             max_value=hi, initial=lo, show_value=False)
        self.input = TextInput(top_left=(X0 + LABEL_W + slide_w + 6, y), width=NUMBER_W,
                               height=24, initial=0.0)
        self.shown: Any = self.input.data.value
        self.slid_shown: Any = self.slider.data.value
        self.owner: Any = None
        self.pending = False        # a drag changed the item, not recorded yet

    def show(self, visible: bool) -> None:
        super().show(visible)
        self.slider.visible = visible

    def set(self, value: Any, owner: Any) -> None:
        super().set(value, owner)
        if self.slider.data.value != self.shown:
            self.slider.data.value = self.shown
        self.slid_shown = self.shown

    def slid(self) -> Optional[float]:
        """The slider's value when it moved since last seen (two decimals,
        as the editor stores numbers), else None. The box follows it."""
        if not self.slider.visible:
            return None
        value = round(float(self.slider.data.value), 2)
        if value == self.slid_shown:
            return None
        self.slid_shown = self.shown = value
        if self.input.data.value != value:
            self.input.data.value = value
        return value

    @property
    def dragging(self) -> bool:
        return _engine.slider_dragging(self.slider)


class _Choice:
    """A labelled drop-down in the properties panel (a concave's Scoop)."""

    def __init__(self, key: str, label: str, y: float, options):
        self.key = key
        self.label = Text(label, top_left=(X0, y - 4), font_size=13)
        self.input = DropDown(top_left=(X0 + LABEL_W, y), width=FIELD_W, height=24,
                              options=list(options), initial=options[0])
        self.shown: Any = options[0]
        self.owner: Any = None

    @property
    def visible(self) -> bool:
        return self.input.visible

    def show(self, visible: bool) -> None:
        self.label.visible = visible
        self.input.visible = visible

    def set(self, value: str, owner: Any) -> None:
        self.owner = owner
        if self.input.data.value != value:
            self.input.data.value = value
        self.shown = value

    def committed(self) -> Optional[str]:
        if not self.input.visible or self.input.data.value == self.shown:
            return None
        self.shown = self.input.data.value
        return self.shown


class _Check:
    def __init__(self, key: str, label: str, y: float):
        self.key = key
        self.box = CheckBox(top_left=(X0, y), size=18, label=label, initial=False)
        self.shown = False
        self.owner = None

    @property
    def visible(self) -> bool:
        return self.box.visible

    def show(self, visible: bool) -> None:
        self.box.visible = visible

    def set(self, value: bool, owner: Any) -> None:
        self.owner = owner
        if self.box.data.value != bool(value):
            self.box.data.value = bool(value)
        self.shown = bool(value)

    def committed(self) -> Optional[bool]:
        if not self.box.visible or self.box.data.value == self.shown:
            return None
        self.shown = self.box.data.value
        return self.shown


class Panel:
    def __init__(self, app):
        self.app = app
        ed: Editor = app.editor
        # Backgrounds (drawn on the ui layer, under the widgets).
        _rect(0, 0, PANEL_LEFT, H, BG)
        _rect(W - PANEL_RIGHT, 0, W, H, BG)
        _rect(0, H - PANEL_TOP, W, H, BG)
        _rect(0, 0, W, PANEL_BOTTOM, BG)

        self.tooltip = Tooltip()
        self.tool_buttons: List[ToolButton] = []

        # -- top bar: file · edit · snap · pointer and view ---------------------------
        # New Open Save Save-as │ Undo Redo │ Snap [grid] │ Select Pan Fit 100%
        y = H - 8
        x = 8.0
        # A tooltip only where it adds something: a shortcut, or a rule the
        # label cannot show. Buttons whose label says it all get none.
        p = PRIMARY
        for label, width, action, keys in (
            (t("file.new"), FILE_W, app.new, f"{p}+N"),
            (t("file.open"), FILE_W, app.open, f"{p}+O"),
            (t("file.save"), FILE_W, app.save, f"{p}+S"),
            (t("file.save_as"), FILE_W, app.save_as, f"{p}+SHIFT+S"),
        ):
            b = Button(top_left=(x, y), width=width, height=28, label=label,
                       on_click=_safe(action, say=app.say))
            attach_tip(b, self.tooltip, _keys_tip(label, keys))
            x += width + 6
        x = self._separator(x)
        self.undo_button = Button(top_left=(x, y), width=EDIT_W, height=28,
                                  label=t("edit.undo"), on_click=_safe(app.undo, say=app.say))
        attach_tip(self.undo_button, self.tooltip, _keys_tip(t("edit.undo"), f"{p}+Z"))
        x += EDIT_W + 6
        self.redo_button = Button(top_left=(x, y), width=EDIT_W, height=28,
                                  label=t("edit.redo"), on_click=_safe(app.redo, say=app.say))
        attach_tip(self.redo_button, self.tooltip, _keys_tip(t("edit.redo"), REDO))
        x += EDIT_W + 6
        x = self._separator(x)
        self.grid_check = CheckBox(top_left=(x, y - 5), size=18, label=t("view.snap"),
                                   initial=ed.snap)
        attach_tip(self.grid_check, self.tooltip, t("tip.snap"))
        x += 112
        self.grid_size = DropDown(top_left=(x, y), width=64, height=28,
                                  options=[str(g) for g in GRID_SIZES],
                                  initial=str(int(ed.grid)))
        x += 64 + 6
        x = self._separator(x)
        for tool, tip in (
            ("select", t("tip.select", name=t("tool.select"), letter=KEY_OF["select"],
                         primary=key_label(PRIMARY))),
            ("hand", t("tip.hand", name=t("tool.hand"), letter=KEY_OF["hand"])),
        ):
            self.tool_buttons.append(ToolButton(
                tool, (x + POINTER_W / 2, y - 14), (POINTER_W, 28),
                _safe(app.choose_tool, tool, say=app.say), tip, self.tooltip,
                tip_side="below"))
            x += POINTER_W + 6
        b = Button(top_left=(x, y), width=50, height=28, label=t("view.fit"),
                   on_click=_safe(ed.fit_view, say=app.say))
        attach_tip(b, self.tooltip, _keys_tip(t("tip.fit"), "F"))
        x += 56
        b = Button(top_left=(x, y), width=56, height=28, label=t("view.actual"),
                   on_click=_safe(ed.actual_size, say=app.say))
        attach_tip(b, self.tooltip, _keys_tip(t("tip.actual"), f"{p}+0"))
        x += 56
        x = self._separator(x)
        # Select group [robo ▾]: a selection command beside the Select tool, as
        # in the reference editors. Its value is computed from the selection
        # (Editor.selected_group): the group's name while the selection is
        # exactly that group, else None; choosing a group selects it, choosing
        # None selects nothing. No tooltip: the label says it, and a tip that
        # pops up while the list is open is in the way.
        self.no_group = t("view.no_group")
        self.group_label = Text(t("view.select_group"), top_left=(x, y - 7), font_size=13)
        x = self.group_label.box.right + 8
        self.group_pick = DropDown(top_left=(x, y), width=GROUP_W, height=28,
                                   options=[self.no_group], initial=self.no_group,
                                   enabled=False)
        self._pick_shown = self.no_group
        self.top_bar_right = x + GROUP_W
        self._grid_shown = (ed.snap, str(int(ed.grid)))

        # -- toolbar: what you create ----------------------------------------------------
        ty = H - PANEL_TOP - 8                  # top edge of the next button
        for tool in CREATE_TOOLS:
            if tool == "image":
                ty -= TOOL_GAP                  # Image opens a file dialog: its own group
            key = KEY_OF[tool]
            self.tool_buttons.append(ToolButton(
                tool, (PANEL_LEFT / 2, ty - TOOL_H / 2), (TOOL_W, TOOL_H),
                _safe(app.choose_tool, tool, say=app.say),
                t("tip.tool", name=t(f"tool.{tool}"), letter=key), self.tooltip, key=key))
            ty -= TOOL_H + 6

        # -- properties panel --------------------------------------------------------------
        top = H - PANEL_TOP - 14
        self.title = Text("", top_left=(X0, top), font_size=15)
        rows = top - 30
        self.fields: Dict[str, _Field] = {}
        # (key, label, row, number). A line's ends share rows with x / y /
        # width / height: the two sets never show together.
        for key, label, row, number in (
            ("name", t("panel.name"), 0, False),
            ("groups", t("panel.groups"), 1, False),
            ("x", t("panel.x"), 2, True),
            ("y", t("panel.y"), 3, True),
            ("x1", t("panel.x1"), 2, True),
            ("y1", t("panel.y1"), 3, True),
            ("x2", t("panel.x2"), 4, True),
            ("y2", t("panel.y2"), 5, True),
            ("width", t("panel.width"), 4, True),
            ("height", t("panel.height"), 5, True),
            ("radius", t("panel.radius"), 6, True),
            ("angle", t("panel.angle"), 7, True),
            ("n", t("panel.sides"), 4, True),         # regular polygons only
            ("rim", t("panel.rim"), 8, False),        # concaves only (no checks there)
        ):
            self.fields[key] = _Field(key, label, rows - row * ROW, number=number)
        # Bounded ratios tuned by eye: a slider and a number box. The slider
        # stays inside the format's range (base_ratio is open at 0 and 2; the
        # box takes any value the format accepts).
        for key, label, lo, hi in (
            ("smooth", t("panel.smooth"), 0.0, 1.0),           # tracks only (no width there)
            ("base_ratio", t("panel.base_ratio"), 0.05, 1.95),  # triangles only
        ):
            self.fields[key] = _Slide(key, label, rows - 4 * ROW, lo, hi)
        # A concave's Scoop sits in the Radius row (a concave has no radius).
        self.choices: Dict[str, _Choice] = {
            "scoop": _Choice("scoop", t("panel.scoop"), rows - 6 * ROW, SCOOPS),
        }
        cy = rows - 8 * ROW - 4
        self.checks: Dict[str, _Check] = {}
        for i, (key, label) in enumerate((
            ("closed", t("panel.closed")),
            ("locked", t("panel.locked")),
            ("guide", t("panel.guide")),
        )):
            self.checks[key] = _Check(key, label, cy - i * 26)
        by = cy - 3 * 26 - 12
        bw = (PANEL_RIGHT - 26) / 2
        self.buttons: List[Button] = []
        # Rows: [Copy as code] · [Duplicate][Delete] · [Front][Back]
        for label, action, col, row, width, keys in (
            (t("panel.copy_code"), _safe(app.copy_code, say=app.say), 0, 0, 2 * bw + 6, None),
            (t("panel.duplicate"), _safe(app.duplicate, say=app.say), 0, 1, bw, f"{p}+D"),
            (t("panel.delete"), _safe(app.delete, say=app.say), 1, 1, bw, "DEL"),
            (t("panel.front"), _safe(app.restack, True, say=app.say), 0, 2, bw, None),
            (t("panel.back"), _safe(app.restack, False, say=app.say), 1, 2, bw, None),
        ):
            b = Button(top_left=(X0 + col * (bw + 6), by - row * 34),
                       width=width, height=28, label=label, on_click=action)
            if keys:   # left of the panel: anywhere else it sits under other widgets
                attach_tip(b, self.tooltip, _keys_tip(label, keys), side="left",
                           edge=W - PANEL_RIGHT - 8)
            self.buttons.append(b)
        # Several selected: Row / Column (the slot of the image row below).
        self.pack_buttons: List[Button] = []
        for col, (label, axis, tip) in enumerate((
            (t("panel.row"), "x", t("tip.row")),
            (t("panel.column"), "y", t("tip.column")),
        )):
            b = Button(top_left=(X0 + col * (bw + 6), by - 3 * 34), width=bw, height=28,
                       label=label, on_click=_safe(app.pack, axis, say=app.say))
            attach_tip(b, self.tooltip, tip, side="left", edge=W - PANEL_RIGHT - 8)
            self.pack_buttons.append(b)
        # One image selected: its file (or sheet · frame), a way to pick another
        # file, and the frame picker (a sheet's frame, or cut this image into one).
        self.image_file = Text("", top_left=(X0, by - 3 * 34 + 2), font_size=12)
        half = (PANEL_RIGHT - 26) / 2
        self.change_image = Button(top_left=(X0, by - 3 * 34 - 18), width=half,
                                   height=28, label=t("panel.change_image"),
                                   on_click=_safe(app.change_image, say=app.say))
        self.choose_frame = Button(top_left=(X0 + half + 6, by - 3 * 34 - 18), width=half,
                                   height=28, label=t("panel.choose_frame"),
                                   on_click=_safe(app.choose_frame, say=app.say))
        # Several selected: the groups they all share (the same field and
        # parsing as for one item), the ones only some have, and X / Y of the
        # selection's box. Owners are tuples of ids.
        self.many: Dict[str, _Field] = {
            "groups": _Field("groups", t("panel.groups"), rows, number=False),
            "x": _Field("x", t("panel.x"), rows - 2 * ROW, number=True),
            "y": _Field("y", t("panel.y"), rows - 3 * ROW, number=True),
        }
        some_top = rows - ROW + 2
        self._some_hover = _rect(X0, some_top - 18, W - 10, some_top, BG)
        self._some_full = ""
        self._some_hover.on_hover = lambda: self.tooltip.request(
            self._some_hover, self._some_full,
            (W - PANEL_RIGHT - 8, some_top - 9), "left")
        self._some_hover.on_hover_exit = lambda: self.tooltip.leave(self._some_hover)
        self.some = Text("", top_left=(X0, some_top), font_size=12)
        # Level size (nothing selected).
        self.level_w = _Field("level_w", t("panel.width"), rows, number=True)
        self.level_h = _Field("level_h", t("panel.height"), rows - ROW, number=True)

        # -- status bar ------------------------------------------------------------------------
        self.status = Text("", top_left=(PANEL_LEFT + 8, PANEL_BOTTOM - 6), font_size=13)
        # Right end: grid and zoom (right-aligned, they change rarely), then the
        # cursor in its own left-aligned Text so nothing shifts as it moves.
        self.status_right = Text("", top_right=(COORD_X - 14, PANEL_BOTTOM - 6), font_size=13)
        self.status_cursor = Text("", top_left=(COORD_X, PANEL_BOTTOM - 6), font_size=13)
        self._seen = None
        self._status_left = None

    def _separator(self, x: float) -> float:
        """A thin rule between top-bar groups; returns where the next group starts."""
        _rect(x + 6, H - PANEL_TOP + 8, x + 7, H - 8, SEPARATOR)
        return x + 20

    def forget_shown(self) -> None:
        """Re-decide every row on the next refresh (the frame picker opened or closed)."""
        self._seen = None

    # -- every frame -----------------------------------------------------------------------
    def poll(self) -> None:
        """Apply what the user committed in the panel since the last frame."""
        ed: Editor = self.app.editor
        for f in self.fields.values():
            value = f.committed()
            if value is not None and f.owner is not None:
                ed.set_field(f.key, value, item_id=f.owner)
                # Show the field as stored ("a;b" → "a, b", "7.0" → 7) even
                # when the edit changed nothing and the doc did not bump.
                self._seen = None
            if isinstance(f, _Slide):
                self._poll_slide(f, ed)
        for c in list(self.checks.values()) + list(self.choices.values()):
            value = c.committed()
            if value is not None and c.owner is not None:
                ed.set_field(c.key, value, item_id=c.owner)
        w = self.level_w.committed()
        h = self.level_h.committed()
        if w is not None or h is not None:
            size = ed.doc.size
            ed.set_size(w if w is not None else size[0], h if h is not None else size[1])
        for key, f in self.many.items():
            value = f.committed()
            if value is None or not f.owner:
                continue
            self._seen = None
            if key == "groups":
                ed.set_groups(value, list(f.owner))
            else:
                ed.move_selection_to(key, value, list(f.owner))
        chosen = self.group_pick.data.value
        if chosen != self._pick_shown:
            # The control mirrors the selection: a group selects it; None while
            # a group shows selects nothing (None while None shows: no change).
            was = self._pick_shown
            self._pick_shown = chosen
            if chosen != self.no_group or was != self.no_group:
                ed.select_group(None if chosen == self.no_group else chosen)
            self._seen = None        # show what the selection now is
        snap = bool(self.grid_check.data.value)
        size = str(self.grid_size.data.value)
        if (snap, size) != self._grid_shown:
            self._grid_shown = (snap, size)
            ed.snap = snap
            ed.grid = float(size)

    def _poll_slide(self, f: _Slide, ed: Editor) -> None:
        """A slider drag changes the item live and is one undo step: each
        move updates the document unrecorded, letting go records it (a
        wheel turn or a click on the track, with no drag, records at once)."""
        value = f.slid()
        if value is not None and f.owner is not None:
            if ed.set_field(f.key, value, item_id=f.owner, record=False):
                f.pending = True
        if f.pending and not f.dragging:
            f.pending = False
            ed.history.commit()

    def refresh(self) -> None:
        """Show the fields for the current selection (when it or the doc changed)."""
        ed: Editor = self.app.editor
        key = (ed.doc.version, tuple(ed.selection), ed.tool)
        standby = ed.select_standby
        for b in self.tool_buttons:
            b.set_active(b.tool == ed.tool)
            b.set_standby(standby and b.tool == "select")
        self.tooltip.tick()
        if self.app.picker is None:      # the picker disables every widget but its own
            for button, able in ((self.undo_button, ed.history.can_undo),
                                 (self.redo_button, ed.history.can_redo)):
                if button.enabled != able:
                    button.enabled = able
        if key == self._seen:
            return
        self._seen = key
        items = ed.selected_items()
        single = items[0] if len(items) == 1 else None
        # Decide every element's visibility first, then apply only the changes:
        # hiding a field that stays shown would drop its keyboard focus (a
        # commit bumps doc.version, which lands here; Tab / Cmd+S keep focus).
        want: Dict[Any, bool] = {}
        for f in self.fields.values():
            want[f] = False
        for c in list(self.checks.values()) + list(self.choices.values()):
            want[c] = False
        want[self.level_w] = want[self.level_h] = False
        for f in self.many.values():
            want[f] = False
        want[self.some] = want[self._some_hover] = False
        groups = ed.doc.groups()
        none = t("view.no_group")
        while none in groups:            # a group named "None" keeps its name
            none = f"({none})"
        if none != self.no_group:
            if self._pick_shown == self.no_group:
                self._pick_shown = none
            self.no_group = none
        options = [self.no_group] + sorted(groups, key=str.casefold)   # easy to scan
        pick = self.group_pick
        if pick.options != options:
            pick.options = options
        if pick.enabled != bool(groups):
            pick.enabled = bool(groups)
        group = ed.selected_group()
        shown = group if group is not None else self.no_group
        if pick.data.value != shown:
            pick.data.value = shown
        self._pick_shown = shown
        for b in self.buttons:
            want[b] = bool(items)
        for b in self.pack_buttons:
            want[b] = len(items) > 1
        is_image = single is not None and single["kind"] == "image"
        want[self.change_image] = want[self.image_file] = want[self.choose_frame] = is_image
        if is_image:
            shown = (single["file"] if single["sheet"] is None
                     else f"{single['sheet']} · {single['frame']}")
            self.image_file.text = fit_text(str(shown), PANEL_RIGHT - 24, 12)
        if single is not None:
            kind = single["kind"]
            self.title.text = t(f"tool.{kind}") + (f"  ·  {single['name']}" if single["name"] else "")
            owner = single["id"]
            cx, cy = _center(single)
            values = {"name": single["name"] or "", "groups": ", ".join(single["groups"])}
            if kind == "line":
                values.update(x1=single["p1"][0], y1=single["p1"][1],
                              x2=single["p2"][0], y2=single["p2"][1])
            else:
                values.update(x=cx, y=cy)
            for k in ("width", "height", "radius", "angle", "smooth", "n", "base_ratio"):
                if k in single:
                    values[k] = single[k]
            if kind == "concave":
                values["rim"] = rim_text(single["rim"])
                self.choices["scoop"].set(single["scoop"], owner)
                want[self.choices["scoop"]] = True
            for k, v in values.items():
                self.fields[k].set(v, owner)
                want[self.fields[k]] = True
            self.checks["locked"].set(single["locked"], owner)
            want[self.checks["locked"]] = True
            if kind == "track":
                self.checks["closed"].set(single["closed"], owner)
                want[self.checks["closed"]] = True
            if kind == "image":
                self.checks["guide"].set(single["guide"], owner)
                want[self.checks["guide"]] = True
        elif items:
            self.title.text = t("panel.selected", count=len(items)) + (
                f"  ·  {group}" if group is not None else "")
            owner = tuple(it["id"] for it in items)
            self.many["groups"].set(", ".join(shared_groups(items)), owner)
            want[self.many["groups"]] = True
            some = partial_groups(items)
            if some:
                self._some_full = ", ".join(some)
                text = t("panel.some", groups=self._some_full)
                self.some.text = text
                if self.some.box.right > W - 12:
                    _fit_end(self.some, text, W - 12)
                want[self.some] = want[self._some_hover] = True
            box = geo_box([it for it in items if not it["locked"]])
            if box is not None:
                self.many["x"].set((box[0] + box[2]) / 2, owner)
                self.many["y"].set((box[1] + box[3]) / 2, owner)
                want[self.many["x"]] = want[self.many["y"]] = True
        else:
            self.title.text = t("panel.level")
            w, h = ed.doc.size
            self.level_w.set(w, "level")
            self.level_h.set(h, "level")
            want[self.level_w] = want[self.level_h] = True
        if self.app.picker is not None:
            # The picker has the right panel: hide every property row.
            want = dict.fromkeys(want, False)
            self.title.text = ""
        for element, visible in want.items():
            _set_visible(element, visible)

    def status_text(self, x: float, y: float) -> None:
        """Left: file (• when unsaved) and the current note or tool hint.
        Right end: grid, zoom and the cursor in Scena units."""
        import os
        app = self.app
        ed: Editor = app.editor
        doc = ed.doc
        name = os.path.basename(doc.path) if doc.path else t("status.untitled")
        if app.dialogs.busy:
            note = t("dialog.busy")
        elif app.picker is not None:
            note = app.picker.status
        else:
            note = ed.message or app.note or ed.hint()
        left = f"{name}{' •' if doc.dirty else ''}    {note}"
        if ed.snap:
            drawn = app.view.grid_step
            grid = t("status.grid", step=f"{ed.grid:g}")
            if drawn and drawn != ed.grid:
                grid += " " + t("status.grid_lines", step=f"{drawn:g}")
        else:
            grid = t("status.no_snap")
        right = f"{grid}    {t('status.zoom', zoom=f'{ed.zoom * 100:.0f}')}"
        cursor = t("status.cursor", x=f"{x:.0f}", y=f"{y:.0f}")
        for text_obj, text in ((self.status_right, right), (self.status_cursor, cursor)):
            if text_obj.text != text:
                text_obj.text = text
        if left != self._status_left:
            self._status_left = left
            self.status.text = left
            limit = self.status_right.box.left - 16
            if self.status.box.right > limit:
                _fit_end(self.status, left, limit)
