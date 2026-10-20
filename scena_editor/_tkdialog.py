"""Fallback file dialog: tkinter in its own process (never next to GLFW).

``python -m scena_editor._tkdialog open|save|image|atlas TITLE START_DIR [DEFAULT_NAME]``
prints the chosen path (nothing on cancel). Tk and GLFW both drive the
macOS application loop, so the editor never imports tkinter itself.
"""
from __future__ import annotations

import sys


def main(argv) -> int:
    kind = argv[1] if len(argv) > 1 else "open"
    title = argv[2] if len(argv) > 2 else ""
    start = argv[3] if len(argv) > 3 else "."
    default = argv[4] if len(argv) > 4 else ""
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError:
        print("scena_editor: no file dialog available (install crossfiledialog or tkinter)",
              file=sys.stderr)
        return 2
    root = tkinter.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tkinter.TclError:
        pass
    if kind == "save":
        path = filedialog.asksaveasfilename(parent=root, title=title, initialdir=start,
                                            initialfile=default, defaultextension=".json",
                                            filetypes=[("Level", "*.json")])
    elif kind == "image":
        path = filedialog.askopenfilename(
            parent=root, title=title, initialdir=start,
            filetypes=[("Images and atlases",
                        "*.png *.jpg *.jpeg *.webp *.gif *.bmp *.svg *.xml *.json"),
                       ("All files", "*")])
    elif kind == "atlas":
        path = filedialog.askopenfilename(
            parent=root, title=title, initialdir=start,
            filetypes=[("Atlases", "*.xml *.json"), ("All files", "*")])
    else:
        path = filedialog.askopenfilename(parent=root, title=title, initialdir=start,
                                          filetypes=[("Level", "*.json")])
    root.destroy()
    if path:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
