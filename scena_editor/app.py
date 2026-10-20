"""The editor application: wires Scena callbacks to the controller, view, panel
and dialogs. ``python -m scena_editor`` builds one ``App`` and runs Scena.
"""
from __future__ import annotations

import functools
import os
import time
import traceback
from typing import Callable, Optional

from scena import Color, Menu, canvas, keyp, mouse
from scena.validate import payload_arity

from . import _engine, dialogs, log, sheets
from .doc import LevelDoc
from .sheet_pick import ATLAS_EXTS, FramePicker, image_for_atlas
from .i18n import t
from .panel import Panel
from .tools import PRIMARY, REDO, Editor
from .view import DESIGN, LevelView, ScenaViewport, over_panel

NOTE_SECONDS = 4.0
PROMPT_FONT = 17
PROMPT_BG = Color(0.24, 0.27, 0.34)   # lighter than the dark panels and canvas


class App:
    def __init__(self, path: Optional[str] = None):
        doc = LevelDoc()
        if path:
            path = os.path.abspath(path)
            if os.path.exists(path):
                doc = LevelDoc.load(path)
            else:
                doc.path = path               # Save writes it
        self.editor = Editor(doc, ScenaViewport())
        self.view = LevelView()
        self.dialogs = dialogs.Runner(after=self._after_dialog)
        self.note = ""
        self._note_until = 0.0
        self._prompt: Optional[Menu] = None
        self.picker: Optional[FramePicker] = None
        self.panel = Panel(self)
        self._title = None
        _engine.set_close_guard(self._close_guard)
        self.editor.fit_view()

    # -- status notes ------------------------------------------------------------------
    def say(self, text: str) -> None:
        self.note = text
        self._note_until = time.monotonic() + NOTE_SECONDS

    # -- input routing ------------------------------------------------------------------
    @property
    def blocked(self) -> bool:
        """A dialog, a prompt or the frame picker is up: the canvas ignores input."""
        return self.dialogs.busy or self._prompt is not None or self.picker is not None

    def _picking(self) -> bool:
        """The frame picker has the canvas (and no dialog of its own is up)."""
        return self.picker is not None and not self.dialogs.busy

    def on_mouse_down(self, x, y, button):
        if self._picking() and not over_panel(x, y):
            self.picker.pointer_down(x, y, button)
            return
        if self.blocked or over_panel(x, y):
            return
        self.editor.message = None
        self.editor.select_held = bool(keyp(PRIMARY))     # fresh at the press
        self.editor.pointer_down(x, y, button, shift=keyp("SHIFT"), space=keyp("SPACE"),
                                 alt=keyp("ALT"))

    def on_mouse_move(self, x, y):
        # Motion is handled here only — Scena also calls on_mouse_drag for the
        # same event while a button is held (Editor Design.md — Spike lessons).
        if self._picking():
            self.picker.pointer_move(x, y)
        elif not self.blocked:
            self.editor.pointer_move(x, y, shift=keyp("SHIFT"), straight=keyp(PRIMARY))

    def on_mouse_up(self, x, y, button, click_x, click_y):
        if self._picking():
            self.picker.pointer_up(x, y, button)
        elif not self.blocked:
            self.editor.pointer_up(x, y, button, shift=keyp("SHIFT"))

    def on_mouse_double_click(self, x, y, button):
        if not self.blocked and not over_panel(x, y):
            self.editor.double_click(x, y)

    def on_mouse_scroll(self, xoffset, yoffset):
        if (self._picking() or not self.blocked) and not over_panel(mouse.x, mouse.y):
            self.editor.zoom_wheel(yoffset, mouse.x, mouse.y)

    def on_key(self, key):
        """Keys with no Cmd / Ctrl / Alt (Scena delivers those to keyp only).

        Shift does not block a key (0.8.1): Shift+arrow nudges by the grid
        here, on the press and its repeats; another Shift+key does nothing.
        """
        if self._picking():
            self.picker.key(key)
            return
        if self.blocked:
            return
        if keyp("SHIFT"):
            if key in ("LEFT", "RIGHT", "UP", "DOWN"):
                self.editor.key(key, shift=True)
            return
        if key == "F":
            self.editor.fit_view()
            return
        if self.editor.tool == "select" and key == "I":
            self.choose_tool("image")
            return
        self.editor.key(key)
        self._take_image_request()

    def _shortcuts(self) -> None:
        p = PRIMARY
        ed = self.editor
        if keyp.once(f"{p}+SHIFT+S"):
            self.save_as()
        elif keyp.once(f"{p}+S"):
            self.save()
        elif keyp.once(f"{p}+O"):
            self.open()
        elif keyp.once(f"{p}+N"):
            self.new()
        elif keyp.once(REDO):
            self.redo()
        elif keyp.once(f"{p}+Z"):
            self.undo()
        elif keyp.once(f"{p}+D"):
            self.duplicate()
        elif keyp.once(f"{p}+C"):
            self.copy()
        elif keyp.once(f"{p}+X"):
            self.cut()
        elif keyp.once(f"{p}+V"):
            self.paste()
        elif keyp.once(f"{p}+A"):
            ed.select_all()
        elif keyp.once(f"{p}+0"):
            ed.actual_size()

    # -- per frame ---------------------------------------------------------------------
    def update(self, dt):
        self.dialogs.poll()
        if self._picking():
            self.picker.update()
            if keyp.once(f"{PRIMARY}+0"):
                self.editor.actual_size()
        if not self.blocked:
            self.panel.poll()
            self._shortcuts()
            self._take_image_request()
        ed = self.editor
        ed.select_held = not self.blocked and bool(keyp(PRIMARY))
        if self.note and time.monotonic() > self._note_until:
            self.note = ""
        self.view.sync(ed)
        self.panel.refresh()
        x, y = mouse.x, mouse.y
        self.panel.status_text(x, y)
        if self.blocked or over_panel(x, y) and ed.gesture is None:
            _engine.set_cursor("arrow")
        else:
            _engine.set_cursor(ed.cursor(x, y, space=keyp("SPACE")))
        name = os.path.basename(ed.doc.path) if ed.doc.path else t("status.untitled")
        title = f"{name}{' •' if ed.doc.dirty else ''} — Scena level editor"
        if title != self._title:
            self._title = title
            _engine.set_title(title)

    # -- dialogs -------------------------------------------------------------------------
    def _after_dialog(self) -> None:
        _engine.forget_key_presses()
        _engine.focus_window()

    def _start_dir(self) -> str:
        return self.editor.doc.base_dir()

    # -- commands --------------------------------------------------------------------------
    def undo(self) -> None:
        """One step back — after the panel's pending commit: a click on the Undo
        button takes focus from a field, and that field's edit must land first."""
        if self.blocked:
            return
        self.panel.poll()
        self.editor.undo()

    def redo(self) -> None:
        if self.blocked:
            return
        self.panel.poll()
        self.editor.redo()

    def choose_tool(self, tool: str) -> None:
        if self.blocked:
            return
        self.editor.set_tool(tool)
        self._take_image_request()

    def _take_image_request(self) -> None:
        ed = self.editor
        if not ed.image_requested or self.dialogs.busy:
            return
        ed.image_requested = False
        ed.tool = "select"
        start = self._start_dir()
        self.dialogs.start(lambda: dialogs.choose_image(start, t("dialog.image_title")),
                           self._place_image)

    def _image_size(self, path: str):
        try:
            import skia
            image = skia.Image.open(path)
            return float(image.width()), float(image.height())
        except Exception as e:  # noqa: BLE001 — any unreadable file
            self.say(t("error.open_failed", file=os.path.basename(path), error=e))
            return None

    def _file_for(self, path: str) -> str:
        doc = self.editor.doc
        return doc.relative_file(path) if doc.path else path

    def _place_image(self, path: Optional[str]) -> None:
        if not path:
            return
        if os.path.splitext(path)[1].lower() in ATLAS_EXTS:
            self._place_from_atlas(path)
            return
        size = self._image_size(path)
        if size is not None:
            self.editor.add_image(self._file_for(path), size, (canvas.pan_x, canvas.pan_y))

    def _place_from_atlas(self, atlas: str) -> None:
        """An atlas from the Image tool: pick one of its frames, placed at the
        middle of the view at its pixel size."""
        png = image_for_atlas(atlas)
        if png is None:
            self.say(t("error.not_an_atlas_image", file=os.path.basename(atlas)))
            return

        def picked(entry, frame, size):
            center = (canvas.pan_x, canvas.pan_y)
            if entry is None:
                self.editor.add_image(self._file_for(png), size, center)
            else:
                self.editor.add_frame(entry, frame, size, center)

        self._open_picker(png, layout={"mode": "atlas", "atlas": atlas}, on_pick=picked)

    def choose_frame(self) -> None:
        """Show another frame in the selected image: the picker on its file
        (its sheet's cut, its frame marked); same center, angle and scale."""
        item = self.editor.single()
        if self.blocked or item is None or item["kind"] != "image":
            return
        self.panel.poll()
        entry = self.editor.doc.sheet(item["sheet"]) if item["sheet"] is not None else None
        file = entry["file"] if entry is not None else self.editor.doc.image_path(item)
        self._pick_into(item, file, entry=entry, current=item["frame"])

    def _pick_into(self, item, file: str, **picker) -> None:
        """Open the picker on ``file`` for an image item: the picked frame (or
        the whole picture) replaces what the item shows, at the item's scale."""
        ed = self.editor
        item_id = item["id"]
        entry = ed.doc.sheet(item["sheet"]) if item["sheet"] is not None else None
        try:
            shown = (sheets.frame_size(entry, item["frame"]) if entry is not None
                     else sheets.image_size(ed.doc.image_path(item)))
        except (ValueError, TypeError):
            shown = (item["width"], item["height"])

        def picked(new_entry, frame, size):
            if not ed.doc.has(item_id):
                return
            if new_entry is None:
                ed.replace_image(item_id, self._file_for(file), size)
            else:
                ed.set_frame(item_id, new_entry, frame, size, shown[1])

        self._open_picker(file, on_pick=picked, **picker)

    def _open_picker(self, file: str, **kwargs) -> None:
        if self.picker is not None:
            return

        def closed():
            self.picker = None
            self.panel.forget_shown()

        self.picker = FramePicker(self, file, on_close=closed, **kwargs)
        self.panel.forget_shown()

    def change_image(self) -> None:
        """Pick another file for the selected image: same center, angle and
        height; the width follows the new picture's proportions."""
        item = self.editor.single()
        if self.blocked or item is None or item["kind"] != "image":
            return
        item_id = item["id"]
        doc = self.editor.doc
        # A frame of a sheet has no file of its own: start at the sheet's.
        shown = doc.sheet(item["sheet"])["file"] if item["sheet"] is not None else doc.image_path(item)
        start = os.path.dirname(shown)

        def replace(path):
            if not path or not self.editor.doc.has(item_id):
                return
            if os.path.splitext(path)[1].lower() in ATLAS_EXTS:
                # An atlas (the dialog takes one): pick which of its frames.
                png = image_for_atlas(path)
                if png is None:
                    self.say(t("error.not_an_atlas_image", file=os.path.basename(path)))
                else:
                    self._pick_into(self.editor.doc.get(item_id), png,
                                    layout={"mode": "atlas", "atlas": path})
                return
            size = self._image_size(path)
            if size is not None:
                self.editor.replace_image(item_id, self._file_for(path), size)

        self.dialogs.start(lambda: dialogs.choose_image(start, t("dialog.image_title")), replace)

    def new(self) -> None:
        self._ask_unsaved(lambda: self.editor.set_doc(LevelDoc()) or self.editor.fit_view())

    def open(self) -> None:
        def pick():
            start = self._start_dir()
            self.dialogs.start(lambda: dialogs.open_level(start, t("dialog.open_title")),
                               self._open_path)
        self._ask_unsaved(pick)

    def _open_path(self, path: Optional[str]) -> None:
        if not path:
            return
        try:
            doc = LevelDoc.load(path)
        except Exception as e:  # noqa: BLE001 — a bad file is reported, not fatal
            self.say(t("error.open_failed", file=os.path.basename(path), error=e))
            return
        self.editor.set_doc(doc)
        self.editor.fit_view()

    def save(self, then: Optional[Callable[[], None]] = None) -> None:
        doc = self.editor.doc
        if not doc.path:
            self.save_as(then)
            return
        self._write(doc.path, then)

    def save_as(self, then: Optional[Callable[[], None]] = None) -> None:
        doc = self.editor.doc
        default = os.path.basename(doc.path) if doc.path else "level.json"
        start = self._start_dir()
        self.dialogs.start(
            lambda: dialogs.save_level_as(start, default, t("dialog.save_title")),
            lambda path: path and self._write(path, then))

    def _write(self, path: str, then: Optional[Callable[[], None]]) -> None:
        try:
            self.editor.doc.save(path)
        except Exception as e:  # noqa: BLE001
            self.say(t("error.save_failed", file=os.path.basename(path), error=e))
            return
        self.say(t("status.saved", file=os.path.basename(path)))
        if then is not None:
            then()

    def copy(self) -> None:
        text = self.editor.copy()
        if text:
            _engine.set_clipboard(text)
            self.say(t("status.copied"))

    def cut(self) -> None:
        text = self.editor.cut()
        if text:
            _engine.set_clipboard(text)

    def paste(self) -> None:
        new = self.editor.paste()
        if new:
            self.say(t("status.pasted", count=len(new)))

    def copy_code(self) -> None:
        text = self.editor.copy_code()
        if text:
            _engine.set_clipboard(text)
            self.say(t("status.copied"))

    def duplicate(self) -> None:
        self.editor.duplicate()

    def delete(self) -> None:
        self.editor.delete()

    def restack(self, front: bool) -> None:
        self.editor.restack(front=front)

    def pack(self, axis: str) -> None:
        self.editor.pack(axis)

    # -- unsaved changes ------------------------------------------------------------------
    def _ask_unsaved(self, then: Callable[[], None]) -> None:
        if not self.editor.doc.dirty:
            then()
            return
        if self._prompt is not None:
            return
        doc = self.editor.doc
        name = os.path.basename(doc.path) if doc.path else t("status.untitled")
        save, discard, cancel = t("prompt.save"), t("prompt.discard"), t("prompt.cancel")

        def chosen(option):
            self._prompt = None
            if option == save:
                self.save(then)
            elif option == discard:
                then()

        self._prompt = Menu(options=[save, discard, cancel], cols=3, on_choose=chosen,
                            title=t("prompt.unsaved", file=name), font_size=PROMPT_FONT,
                            background=PROMPT_BG, color="white")

    def _close_guard(self) -> bool:
        if not self.editor.doc.dirty:
            return True
        self._ask_unsaved(_engine.close_now)
        return False


def guarded(app: "App", fn: Callable) -> Callable:
    """Run ``fn``; on an exception print it and say so in the status bar.

    An editor bug must not close the window and lose unsaved work (in Scena
    an exception in a callback ends ``run()``). The gesture in progress is
    dropped so the document stays consistent.
    """
    # Scena passes a callback only the arguments it asks for (update(dt) vs
    # update(dt, canvas)); this wrapper takes *args, so it trims them by the
    # same rule for the callback it wraps.
    takes = payload_arity(fn)

    @functools.wraps(fn)
    def call(*args):
        try:
            return fn(*(args if takes is None else args[:takes]))
        except Exception as e:  # noqa: BLE001 — report, keep the editor alive
            traceback.print_exc()
            path = log.write_error(e, getattr(fn, "__name__", "callback"))
            try:
                app.editor.cancel()
            except Exception:  # noqa: BLE001
                pass
            app.say(t("error.internal", error=f"{type(e).__name__}: {e}", log=path))
    return call


def callbacks(app: App) -> dict:
    """The script callbacks Scena's ``run()`` picks up from the caller's globals."""
    return {name: guarded(app, fn) for name, fn in (
        ("update", app.update),
        ("on_mouse_down", app.on_mouse_down),
        ("on_mouse_move", app.on_mouse_move),
        ("on_mouse_up", app.on_mouse_up),
        ("on_mouse_double_click", app.on_mouse_double_click),
        ("on_mouse_scroll", app.on_mouse_scroll),
        ("on_key", app.on_key),
    )}
