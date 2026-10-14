"""Editor UI strings. Every label goes through :func:`t`.

Only English ships. A second language is one more table in ``STRINGS`` with
the same keys (``test_editor_i18n`` checks that every table has every key and
that every ``t("…")`` in the editor names a real key).
"""
from __future__ import annotations

STRINGS = {
    "en": {
        # tools
        "tool.select": "Select",
        "tool.hand": "Pan",
        "tool.rect": "Rect",
        "tool.ellipse": "Ellipse",
        "tool.circle": "Circle",
        "tool.line": "Line",
        "tool.polygon": "Polygon",
        "tool.regular_polygon": "Regular polygon",
        "tool.track": "Track",
        "tool.point": "Point",
        "tool.image": "Image",
        # tool hints (status bar)
        "hint.select": "Click selects · Shift adds · drag on empty canvas: box · {alt}+drag copies · Space+drag pans",
        "hint.move": "Moving · hold {primary}: straight · Shift: no snap",
        "hint.hand": "Drag to move the view · {primary}+click / drag: select",
        "hint.rect": "Drag to draw a rectangle (a click makes 100 × 100) · Shift: no snap · Esc: cancel",
        "hint.ellipse": "Drag to draw an ellipse (a click makes 100 × 100) · Shift: no snap · Esc: cancel",
        "hint.circle": "Drag from the center out (a click makes radius 50) · Shift: no snap · Esc: cancel",
        "hint.line": "Drag from one end to the other (a click makes 100 long) · Shift: no snap · Esc: cancel",
        "hint.polygon": "Click to add corners · Enter or double-click closes it · Esc: cancel",
        "hint.regular_polygon": "Drag from the center out (a click makes radius 50) · Sides in the panel · Shift: no snap · Esc: cancel",
        "hint.track": "Click to add points · Enter or double-click finishes · Esc: cancel",
        "hint.point": "Click to place a point",
        "hint.image": "Choose an image file",
        # tooltips
        "tip.tool": "{name} ({letter})",
        "tip.hand": "{name} ({letter}) · or hold Space and drag",
        "tip.keys": "{name} ({keys})",
        "tip.select": "{name} ({letter}) · or hold {primary} in any tool",
        "tip.snap": "Hold Shift while dragging: no snap",
        "tip.fit": "Fit the level in view",
        "tip.actual": "Actual size",
        "tip.row": "Edge to edge, left to right from the leftmost item, no gaps",
        "tip.column": "Edge to edge, bottom to top from the lowest item, no gaps",
        # top bar
        "edit.undo": "Undo",
        "edit.redo": "Redo",
        "file.new": "New",
        "file.open": "Open…",
        "file.save": "Save",
        "file.save_as": "Save as…",
        "view.snap": "Snap to grid",
        "view.fit": "Fit",
        "view.actual": "100%",
        "view.select_group": "Select group",
        "view.no_group": "None",
        # panel
        "panel.level": "Level",
        "panel.width": "Width",
        "panel.height": "Height",
        "panel.name": "Name",
        "panel.groups": "Groups",
        "panel.groups_hint": "comma-separated",
        "panel.x": "X",
        "panel.y": "Y",
        "panel.x1": "X1",
        "panel.y1": "Y1",
        "panel.x2": "X2",
        "panel.y2": "Y2",
        "panel.radius": "Radius",
        "panel.angle": "Angle",
        "panel.smooth": "Smooth",
        "panel.sides": "Sides",
        "panel.closed": "Closed",
        "panel.locked": "Locked",
        "panel.guide": "Guide (editor only)",
        "panel.change_image": "Change image…",
        "panel.copy_code": "Copy as code",
        "panel.duplicate": "Duplicate",
        "panel.delete": "Delete",
        "panel.front": "Front",
        "panel.back": "Back",
        "panel.selected": "{count} selected",
        "panel.some": "Some: {groups}",
        "panel.row": "Row",
        "panel.column": "Column",
        # status
        "status.cursor": "({x}, {y})",
        "status.grid": "grid {step}",
        "status.grid_lines": "(lines every {step})",
        "status.no_snap": "no snap",
        "status.zoom": "zoom {zoom}%",
        "status.untitled": "untitled",
        "status.copied": "Copied — Cmd/Ctrl+V pastes here; the code is on the clipboard",
        "status.pasted": "Pasted {count}",
        "status.saved": "Saved {file}",
        # notes after an edit (status bar)
        "note.groups": "Groups: {groups}",
        "note.no_groups": "No groups",
        "note.group_added": "added \"{name}\" to {items}",
        "note.group_removed": "removed \"{name}\" from {items}",
        "note.new_group": "\"{name}\" is a new group.",
        "note.row": "Placed {count} items in a row",
        "note.column": "Placed {count} items in a column",
        "note.item_one": "1 item",
        "note.item_many": "{count} items",
        # dialogs and prompts
        "dialog.busy": "A file dialog is open — finish it first.",
        "dialog.open_title": "Open level",
        "dialog.save_title": "Save level",
        "dialog.image_title": "Choose an image",
        "prompt.unsaved": "Save changes to {file}?",
        "prompt.save": "Save",
        "prompt.discard": "Don't save",
        "prompt.cancel": "Cancel",
        # errors shown in the status bar
        "error.name_taken": "The name {name!r} is already used",
        "error.open_failed": "Could not open {file}: {error}",
        "error.save_failed": "Could not save {file}: {error}",
        "error.internal": "Editor error: {error} — details in {log}",
    },
}

LANG = "en"


def t(key: str, **fields) -> str:
    """The UI string for ``key`` in the current language, formatted with ``fields``."""
    table = STRINGS.get(LANG, STRINGS["en"])
    text = table.get(key)
    if text is None:
        text = STRINGS["en"][key]   # KeyError on an unknown key: a bug, caught by tests
    return text.format(**fields) if fields else text
