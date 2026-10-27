"""Pick pyGLFW's X11 build on Linux before ``glfw`` loads.

pyGLFW's Linux wheel carries two GLFW builds and loads the Wayland one when
``XDG_SESSION_TYPE=wayland`` (Ubuntu's default session). That build makes an
EGL context, and skia-python's ``GrDirectContext.MakeGL()`` looks for a GLX
one on Linux: it returns None and no window can draw. The X11 build runs
through XWayland on a Wayland desktop and gives Skia the GLX context it finds.

The import of ``scena`` runs this first (``scena/__init__.py``); a variant the
user set stays theirs. See ``design/Scena Design.md``, "Linux and Wayland".
"""
from __future__ import annotations

import os
import sys

VARIANT_ENV = "PYGLFW_LIBRARY_VARIANT"


def prefer_x11(environ=None, platform: str | None = None) -> bool:
    """Set ``PYGLFW_LIBRARY_VARIANT=x11`` on Linux unless already set.

    Returns True when it set the variable.
    """
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if not platform.startswith("linux") or environ.get(VARIANT_ENV):
        return False
    environ[VARIANT_ENV] = "x11"
    return True


def no_gl_context_message(
    environ=None, platform: str | None = None, glfw_loaded_first: bool | None = None
) -> str:
    """The error when Skia finds no OpenGL context for the window."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if glfw_loaded_first is None:
        glfw_loaded_first = GLFW_LOADED_FIRST
    msg = "Skia found no OpenGL context for the window (GrDirectContext.MakeGL() returned None)."
    if platform.startswith("linux"):
        variant = environ.get(VARIANT_ENV, "")
        if variant.lower() == "wayland":
            msg += (
                f" {VARIANT_ENV}=wayland loads GLFW's Wayland build, whose EGL context"
                f" Skia cannot use: unset it or set {VARIANT_ENV}=x11."
            )
        elif glfw_loaded_first:
            msg += (
                " glfw was imported before scena, so it may have loaded GLFW's Wayland"
                f" build: import scena first, or run with {VARIANT_ENV}=x11."
            )
        else:
            msg += " Check that the graphics driver provides OpenGL 3.2 (glxinfo -B)."
    else:
        msg += " Check that the graphics driver provides OpenGL 3.2."
    return msg


# A script that imported glfw before scena already chose its GLFW build.
GLFW_LOADED_FIRST = "glfw" in sys.modules
prefer_x11()
