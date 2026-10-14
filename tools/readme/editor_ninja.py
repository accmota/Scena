"""The README's picture of the level editor: Ninja IV's level, open for editing.

Not an example (the editor is started with ``scena-editor``): this is what
``scena_editor.__main__`` does, with the level file given, so
``tools/readme/make_readme_media.py`` can play it headless like any program.
"""
import os

from scena import *

init(width=1280, height=800, title="Scena level editor")

from scena_editor.app import App, callbacks

LEVEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                     "examples", "media", "levels", "ninja_perigos.json")
app = App(os.path.normpath(LEVEL))
globals().update(callbacks(app))

run()
