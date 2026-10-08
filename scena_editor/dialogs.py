"""Native file dialogs: Open level, Save level as, Choose image.

Backend: ``crossfiledialog`` (a Scena dependency; osascript on
macOS, COM on Windows, zenity / kdialog on Linux), else tkinter in a child
process (``python -m scena_editor._tkdialog``). ``SCENA_EDITOR_DIALOGS=tk``
forces the fallback. Each call returns an absolute path or ``None``.

:class:`Runner` runs one dialog at a time without freezing the window
(a worker thread on macOS / Linux, where the dialog is another process;
on the main thread on Windows, where the COM dialog is modal). The host
polls it every frame. Lessons from the spike (Editor Design.md): macOS
Cancel raises ``OsascriptException (-128)``; the macOS save panel adds no
extension; afterwards drop key presses made during the dialog and take the
keyboard focus back.

macOS Open dialogs are our own ``choose file`` script: AppleScript's
``of type`` takes Uniform Type Identifiers (``public.json``), and
``crossfiledialog`` passes bare extensions (``{"json"}``), which match no
file — every file showed grayed out.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Callable, List, Optional

IMAGE_TYPES = ("png", "jpg", "jpeg", "webp", "gif", "bmp", "svg")
# macOS ``choose file of type``: UTIs, never extensions. ``public.image``
# covers every IMAGE_TYPES entry (svg, webp and gif conform to it).
LEVEL_UTIS = ("public.json",)
IMAGE_UTIS = ("public.image",)
MACOS = sys.platform == "darwin"


# -- backends --------------------------------------------------------------------------

def _crossfiledialog():
    if os.environ.get("SCENA_EDITOR_DIALOGS", "").lower() == "tk":
        return None
    try:
        import crossfiledialog            # noqa: F401  (raises on Linux without zenity/kdialog)
    except Exception:  # noqa: BLE001 — any failure means: use the fallback
        return None
    return crossfiledialog


def _is_cancel(error: BaseException) -> bool:
    return "(-128)" in str(error) or "cancel" in str(error).lower()


def _tk(kind: str, title: str, start_dir: str, default_name: str = "") -> Optional[str]:
    cmd = [sys.executable, "-m", "scena_editor._tkdialog", kind, title, start_dir, default_name]
    try:
        # The child prints the path; pin UTF-8 both ways (Windows pipes default
        # to the locale, cp1252: a path outside it would crash or garble).
        out = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                             timeout=3600, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except (OSError, subprocess.SubprocessError):
        return None
    path = out.stdout.strip()
    return path or None


def _quote(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def choose_file_script(title: str, start_dir: str, utis) -> str:
    """The AppleScript for a macOS Open dialog that accepts the ``utis``."""
    script = f"set chosenFile to choose file with prompt {_quote(title)}"
    if start_dir:
        script += f" default location POSIX file {_quote(start_dir)}"
    script += " of type {" + ", ".join(_quote(u) for u in utis) + "}"
    return script + "\nPOSIX path of chosenFile"


def _osascript(script: str) -> str:
    """Run ``script``; a failure (Cancel is ``(-128)``) raises with osascript's message."""
    out = subprocess.run(["osascript", "-e", script], capture_output=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"osascript exit {out.returncode}")
    return out.stdout.strip()


def _open(kind: str, title: str, start_dir: str, patterns, utis) -> Optional[str]:
    """An Open dialog: our AppleScript on macOS, ``crossfiledialog`` elsewhere,
    tkinter when neither works. Cancel → ``None`` (no fallback)."""
    cfd = _crossfiledialog()
    if cfd is not None:
        try:
            if MACOS:
                return _absolute(_osascript(choose_file_script(title, start_dir, utis)))
            return _absolute(cfd.open_file(title=title, start_dir=start_dir, filter=patterns))
        except Exception as e:  # noqa: BLE001
            if _is_cancel(e):
                return None
    return _absolute(_tk(kind, title, start_dir))


def _absolute(path) -> Optional[str]:
    if not path:
        return None
    if isinstance(path, (list, tuple)):
        path = path[0] if path else None
        if not path:
            return None
    return os.path.abspath(str(path))


def open_level(start_dir: str, title: str = "Open level") -> Optional[str]:
    return _open("open", title, start_dir, "*.json", LEVEL_UTIS)


def save_level_as(start_dir: str, default_name: str = "level.json",
                  title: str = "Save level") -> Optional[str]:
    cfd = _crossfiledialog()
    path = None
    done = False
    if cfd is not None:
        try:
            if sys.platform == "win32":
                path = cfd.save_file(title=title, start_dir=start_dir, filter="*.json",
                                     default_name=default_name)
            else:
                path = cfd.save_file(title=title, start_dir=start_dir)
            done = True
        except Exception as e:  # noqa: BLE001
            if _is_cancel(e):
                return None
    if not done:
        path = _tk("save", title, start_dir, default_name)
    path = _absolute(path)
    if path and not path.lower().endswith(".json"):
        path += ".json"                    # the macOS panel adds no extension
    return path


def choose_image(start_dir: str, title: str = "Choose an image") -> Optional[str]:
    return _open("image", title, start_dir, [f"*.{ext}" for ext in IMAGE_TYPES], IMAGE_UTIS)


# -- one dialog at a time, polled by the host ----------------------------------------

class Runner:
    def __init__(self, *, threaded: Optional[bool] = None,
                 after: Optional[Callable[[], None]] = None):
        """``threaded``: run dialogs in a worker thread (default: not on Windows).
        ``after``: called on the main thread when a dialog ends (drop stale key
        presses, refocus the window)."""
        self.threaded = (sys.platform != "win32") if threaded is None else threaded
        self.after = after
        self._thread: Optional[threading.Thread] = None
        self._result: List = []
        self._then: Optional[Callable[[Optional[str]], None]] = None

    @property
    def busy(self) -> bool:
        return self._then is not None

    def start(self, fn: Callable[[], Optional[str]],
              then: Callable[[Optional[str]], None]) -> bool:
        """Run ``fn()`` (a dialog); ``then(path_or_None)`` runs on the main
        thread from :meth:`poll`. False (and nothing happens) when busy."""
        if self.busy:
            return False
        self._then = then
        self._result = []

        def work():
            try:
                self._result.append(fn())
            except Exception:  # noqa: BLE001 — a broken dialog is a cancel
                self._result.append(None)

        if self.threaded:
            self._thread = threading.Thread(target=work, daemon=True)
            self._thread.start()
        else:
            work()
            self.poll()
        return True

    def poll(self) -> None:
        """Call every frame: delivers a finished dialog's result."""
        if self._then is None or not self._result:
            return
        then, self._then = self._then, None
        result = self._result[0]
        self._thread = None
        if self.after is not None:
            self.after()
        then(result)
