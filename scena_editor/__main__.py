"""The Scena level editor.

    scena-editor [level.json]            (installed by pip with Scena)
    python -m scena_editor [level.json]  (the same, through a given Python)
    scena-editor --shortcut              (once: a launcher icon for this system)
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else list(argv))
    if args.shortcut:
        return _shortcut()
    from . import log
    try:
        from scena import init, run
        init(width=1280, height=800, title="Scena level editor")
        from .app import App, callbacks
        app = App(args.level)
        globals().update(callbacks(app))   # run() reads the callbacks from these globals
        run()
    except Exception as e:  # noqa: BLE001 — started from an icon, the log is all there is
        path = log.write_error(e, "start" if "app" not in locals() else "run")
        print(f"Scena editor stopped with an error: {type(e).__name__}: {e}\n"
              f"Details: {path}", file=sys.stderr)
        return 1
    return 0


def _parse(argv):
    parser = argparse.ArgumentParser(
        prog="scena-editor",
        description="Scena level editor: place geometry, save a level file that games "
                    "read with scena.Level. Also: python -m scena_editor.")
    parser.add_argument("level", nargs="?", help="level file to open (created on first save)")
    parser.add_argument("--shortcut", action="store_true",
                        help="create a launcher icon for this system (Start menu and desktop "
                             "on Windows, ~/Applications on macOS, the applications menu on "
                             "Linux) and exit")
    return parser.parse_args(argv)


def _shortcut() -> int:
    from . import shortcut
    try:
        made = shortcut.create()
    except Exception as e:  # noqa: BLE001
        print(f"Could not create the launcher: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print("Scena Editor launcher created:")
    for path in made:
        print(f"  {path}")
    removed = shortcut.remove_legacy()
    if removed:
        print("Removed the old Stage Editor launcher (before 0.6.0):")
        for path in removed:
            print(f"  {path}")
    print(f"It starts the editor with {sys.executable}. "
          "Run 'scena-editor --shortcut' again if you reinstall Python.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
