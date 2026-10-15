"""Every Scena private the editor uses, in one place (the boundary adapter).

``scena_editor/tests/test_boundary.py`` fails if a Scena private appears in
any other editor module. Each function here is a candidate for a public API;
see ``design/Editor Design.md`` (Boundary).
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

import glfw


def framework():
    from scena.orchestration import ScenaFramework
    return ScenaFramework.get_instance()


def window():
    """The GLFW window, or None before ``run()`` opens it."""
    return getattr(framework(), "_window", None)


def set_close_guard(guard: Optional[Callable[[], bool]]) -> None:
    """``guard()`` runs on a window close request (and Ctrl+Shift+Z); False keeps it open."""
    framework()._close_guard = guard


def close_now() -> None:
    """Close the window without asking the guard (after the user chose)."""
    fw = framework()
    fw._close_guard = None
    win = window()
    if win is not None:
        glfw.set_window_should_close(win, True)
    fw._running = False


def set_title(text: str) -> None:
    win = window()
    if win is not None:
        glfw.set_window_title(win, text)


def set_clipboard(text: str) -> None:
    win = window()
    if win is not None:
        glfw.set_clipboard_string(win, text)


def focus_window() -> None:
    """Take keyboard focus back (after a file dialog in another process)."""
    win = window()
    if win is not None:
        glfw.focus_window(win)


def forget_key_presses() -> None:
    """Drop key presses that arrived while a dialog was open, so they do not
    fire ``keyp.once`` afterwards (the spike's stale Cmd+O)."""
    import builtins
    keyp = getattr(builtins, "keyp", None)
    if keyp is not None:
        keyp._swallow_edges()


# -- cursors -----------------------------------------------------------------------

_STANDARD = {
    "arrow": glfw.ARROW_CURSOR,
    "move": glfw.RESIZE_ALL_CURSOR,
    "cross": glfw.CROSSHAIR_CURSOR,
    "ew": glfw.RESIZE_EW_CURSOR,
    "ns": glfw.RESIZE_NS_CURSOR,
    "nwse": glfw.RESIZE_NWSE_CURSOR,
    "nesw": glfw.RESIZE_NESW_CURSOR,
    "text": glfw.IBEAM_CURSOR,
}
_cursors: Dict[str, object] = {}
_current = [None]


def _rotate_image():
    """A curved-arrow cursor (32×32 RGBA), drawn with Skia."""
    import skia
    n = 32
    surf = skia.Surface(n, n)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    for color, width in ((skia.ColorWHITE, 5), (skia.ColorBLACK, 2)):
        stroke = skia.Paint(AntiAlias=True, Color=color, Style=skia.Paint.kStroke_Style,
                            StrokeWidth=width)
        c.drawArc(skia.Rect.MakeXYWH(7, 7, 18, 18), 200, 250, False, stroke)
        tip = skia.Path()
        tip.moveTo(25, 12)
        tip.lineTo(29, 19)
        tip.lineTo(21, 18)
        tip.close()
        fill = skia.Paint(AntiAlias=True, Color=color,
                          Style=skia.Paint.kStrokeAndFill_Style, StrokeWidth=width - 1)
        c.drawPath(tip, fill)
    return (n, n, surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))


def set_cursor(name: str) -> None:
    """``arrow`` / ``move`` / ``cross`` / ``ew`` / ``ns`` / ``nwse`` / ``nesw`` /
    ``rotate`` / ``text``. Cheap when unchanged."""
    win = window()
    if win is None or name == _current[0]:
        return
    cursor = _cursors.get(name)
    if cursor is None:
        if name == "rotate":
            cursor = glfw.create_cursor(_rotate_image(), 16, 16)
        else:
            cursor = glfw.create_standard_cursor(_STANDARD.get(name, glfw.ARROW_CURSOR))
        _cursors[name] = cursor
    glfw.set_cursor(win, cursor)
    _current[0] = name


def track_curve(points, *, closed: bool, smooth: float):
    """The polyline a ``Track(points, smooth=, closed=)`` draws (default
    quality), in the same coordinates as ``points``."""
    from scena.curves import flatten_controls, samples_per_segment_for
    xs, ys = flatten_controls(points, closed=closed, smooth=smooth,
                              samples_per_segment=samples_per_segment_for("high"))
    return list(zip(xs, ys))


def slider_dragging(slider) -> bool:
    """True while the pointer holds ``slider``'s handle. Scena's ``Slider``
    has no public drag-ended signal; the panel records one undo step when
    the handle is let go."""
    return bool(getattr(slider, "_dragging_handle", False))
