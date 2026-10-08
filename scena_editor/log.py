"""The editor's error log: started from an icon there is no terminal to read.

Every error the editor reports (a failed callback, a crash at start) is
appended here with its traceback; the status bar names the file.
"""
from __future__ import annotations

import datetime
import os
import sys
import traceback
from typing import Optional

MAX_BYTES = 1_000_000          # past this the log starts over (one old copy kept)


def log_path(platform: Optional[str] = None, home: Optional[str] = None,
             env: Optional[dict] = None) -> str:
    """Where errors go: the usual per-user log place of each system."""
    platform = platform or sys.platform
    home = home or os.path.expanduser("~")
    env = os.environ if env is None else env
    if platform == "darwin":
        return os.path.join(home, "Library", "Logs", "Scena Editor", "editor.log")
    if platform == "win32":
        base = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(base, "Scena Editor", "editor.log")
    base = env.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")
    return os.path.join(base, "scena-editor", "editor.log")


def write_error(error: BaseException, where: str = "", path: Optional[str] = None) -> str:
    """Append ``error`` (with its traceback) to the log; return the log path.
    Never raises: logging must not hide the error it reports."""
    path = path or log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
            os.replace(path, path + ".1")
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"--- {stamp} {where}\n{text}\n")
    except OSError:
        pass
    return path
