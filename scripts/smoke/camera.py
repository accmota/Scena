"""
camera.py — smoke: timed camera (time= / ease= / channels / about=).

Separate from world_view.py (parallax / cull). Here: pan/zoom/rotate/frame/
set_origin/reset_view with time=, channel cancel, about= glue.

Keys
----
  A / S     previous / next vignette
  SPACE     replay current tween
  R         snap reset_view (instant)

Usage
-----
    python scripts/smoke/camera.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.8, title="Smoke — timed camera")
canvas.background = (0.06, 0.07, 0.10)
canvas.set_origin("center")

hud = SmokeHud(
    title="Timed camera",
    expect="A/S vignettes · SPACE replay · gold = look / focus target",
    keys="A/S vignette  ·  SPACE replay  ·  R snap reset",
    status="",
    show_aux=True,
    aux="camera …",
)

_owned = []
_marker = None
_mode_i = 0
_handles = []
_tip = ""


def _track(obj):
    _owned.append(obj)
    return obj


def _clear():
    global _marker
    for o in list(_owned):
        try:
            o.destroy()
        except Exception:
            pass
    _owned.clear()
    _marker = None
    canvas.background.clear()
    canvas.background.base = Color(0.06, 0.07, 0.10)
    # Never clear ``ui`` — SmokeHud Text lives there.
    for name in list(canvas.layers):
        if name in ("default", "top"):
            canvas.layers[name].clear(hard=True)
        elif name != "ui":
            try:
                canvas.layers[name].delete(destroy_shapes=True)
            except Exception:
                pass


def _grid():
    grid_c = Color(1, 1, 1, 0.12)
    for x in range(-800, 801, 100):
        _track(Line(p1=(x, -500), p2=(x, 500)).set_color(grid_c)).line_width = 1
    for y in range(-500, 501, 100):
        _track(Line(p1=(-800, y), p2=(800, y)).set_color(grid_c)).line_width = 1
    _track(Circle(center=(0, 0), radius=14).set_color("cyan"))
    for label, xy, col in (
        ("A", (-300, 200), "coral"),
        ("B", (300, 200), "gold"),
        ("C", (-300, -200), "lime"),
        ("D", (300, -200), "violet"),
    ):
        _track(Circle(center=xy, radius=28).set_color(col))
        _track(
            Text(
                text=label,
                center=xy,
                font_size=18,
                color=Color(0.05, 0.05, 0.08),
            )
        )


def _label(xy, text, *, color=Color(1, 0.85, 0.4)):
    _track(
        Text(
            text=text,
            center=(xy[0], xy[1] + 36),
            font_size=14,
            color=color,
        )
    )


def _place_marker(xy=(220, 120)):
    """Orange about= point (stays glued when zoom/rotate use about=)."""
    global _marker
    _marker = _track(Circle(center=xy, radius=22).set_color(Color(1, 0.35, 0.2)))
    _marker.line = "white"
    _marker.line_width = 3
    _label(xy, "about=", color=Color(1, 0.7, 0.5))
    return xy


def _look_target(xy, *, label="look"):
    """Gold crosshair at the pan / look destination (should end under view center)."""
    x, y = xy
    arm = 36
    c = Color(1.0, 0.82, 0.25, 1)
    for p1, p2 in (
        ((x - arm, y), (x + arm, y)),
        ((x, y - arm), (x, y + arm)),
    ):
        ln = _track(Line(p1=p1, p2=p2).set_color(c))
        ln.line_width = 3
    ring = _track(Circle(center=xy, radius=18).set_color(Color(1, 0.82, 0.25, 0.15)))
    ring.line = c
    ring.line_width = 2
    _label(xy, label, color=c)
    return xy


def _focus_frame(cx, cy, w, h, *, angle=0.0, pad=0.15, label="focus"):
    """Inner target + outer padded stroke.

    After ``frame_to(..., pad=)``, the outer box should fill the view and
    the inner box should sit inset with a visible margin.
    """
    p = float(pad)
    outer_w = w * (1.0 + 2.0 * p)
    outer_h = h * (1.0 + 2.0 * p)

    outer = _track(
        Rect(center=(cx, cy), width=outer_w, height=outer_h, angle=angle).set_color(
            Color(0.2, 0.9, 0.55, 0.08)
        )
    )
    outer.line = Color(0.3, 1.0, 0.55, 0.9)
    outer.line_width = 2

    inner = _track(
        Rect(center=(cx, cy), width=w, height=h, angle=angle).set_color(
            Color(0.3, 0.55, 0.95, 0.35)
        )
    )
    inner.line = "skyblue"
    inner.line_width = 3
    _label(
        (cx, cy - h * 0.5 - 10),
        f"{label}  pad={p:.2f}",
        color=Color(0.6, 0.9, 1.0),
    )
    return inner


def _set_tip(text: str) -> None:
    global _tip
    _tip = text
    hud.expect = text


def _cancel_handles():
    for h in _handles:
        try:
            h.cancel()
        except Exception:
            pass
    _handles.clear()


def _start(*handles):
    _cancel_handles()
    for h in handles:
        if h is not None:
            _handles.append(h)


MODES = []


def _mode(label):
    def deco(fn):
        MODES.append((label, fn))
        return fn

    return deco


@_mode("1 pan_to — gold crosshair under view center")
def _v_pan():
    _grid()
    dest = (280, 60)
    _look_target(dest, label="look → pan_to")
    _place_marker((-120, -80))
    canvas.reset_view()
    canvas.set_origin("center")
    canvas.pan_to(0, 0)
    _start(canvas.pan_to(dest[0], dest[1], time=0.9, ease="ease_out"))
    _set_tip("Expect: gold crosshair settles under view center")


@_mode("2 zoom about= — orange marker glued on screen")
def _v_zoom_about():
    _grid()
    about = _place_marker((180, 80))
    canvas.reset_view()
    canvas.set_origin("center")
    canvas.pan_to(0, 0)
    _start(canvas.zoom_to(2.4, about=about, time=1.0, ease="ease_in_out"))
    _set_tip("Expect: orange about= stays fixed on screen while world zooms")


@_mode("3 pan + zoom — look target + zoom (no about=)")
def _v_combine():
    _grid()
    dest = (250, -40)
    _look_target(dest, label="look → pan")
    _place_marker((-200, 150))
    canvas.reset_view()
    canvas.set_origin("center")
    canvas.pan_to(0, 0)
    _start(
        canvas.pan_to(dest[0], dest[1], time=1.0, ease="ease_out"),
        canvas.zoom_to(1.8, time=1.0, ease="ease_out"),
    )
    _set_tip("Expect: gold under center AND zoom≈1.8 (channels run together)")


@_mode("4 rotate about= — marker glued, shortest arc")
def _v_rotate():
    _grid()
    about = _place_marker((150, 0))
    canvas.reset_view()
    canvas.set_origin("center")
    canvas.pan_to(0, 0)
    canvas.rotate_to(350)
    _start(canvas.rotate_to(10, about=about, time=0.8, ease="ease_in_out"))
    _set_tip("Expect: orange glued; rotation 350→10 via short +20° (not −340°)")


@_mode("5 cancel — pan wins; marker may slide")
def _v_cancel():
    _grid()
    about = _place_marker((200, 100))
    dest = (-200, -80)
    _look_target(dest, label="look → pan wins")
    canvas.reset_view()
    canvas.set_origin("center")
    canvas.pan_to(0, 0)
    h_zoom = canvas.zoom_to(3.0, about=about, time=1.2)
    h_pan = canvas.pan_to(dest[0], dest[1], time=1.0, ease="ease_out")
    _start(h_zoom, h_pan)
    _set_tip("Expect: gold under center; zoom stays ~1 (about-zoom cancelled)")


@_mode("6 frame_to — green outer = padded view fill")
def _v_frame():
    _grid()
    _place_marker((-250, 180))
    focus = _focus_frame(320, -120, 220, 140, angle=18.0, pad=0.15)
    canvas.reset_view()
    canvas.set_origin("center")
    canvas.pan_to(0, 0)
    _start(
        canvas.frame_to(focus, pad=0.15, rotate=True, time=1.1, ease="ease_in_out")
    )
    _set_tip("Expect: green outer fills window; blue inner inset with margin")


@_mode("7 set_origin center — (0,0) to view center; rest=look")
def _v_origin():
    _grid()
    _look_target((0, 0), label="origin (0,0) → center")
    _place_marker((220, 120))
    canvas.background.base = SkyGradient("night")
    canvas.background.add(Stars(pan_response=0.2, amount=0.7))
    canvas.reset_view()
    canvas.pan_to(200, 100)
    _start(canvas.set_origin("center", time=1.0, ease="ease_out"))
    _set_tip("Expect: cyan (0,0) under center; rest equals look (stars don't pop)")


@_mode("8 reset_view — back to identity look (design center)")
def _v_reset():
    _grid()
    # Identity look is design center even after set_origin('center').
    ident = (W * 0.5, H * 0.5)
    _look_target(ident, label="identity look")
    _focus_frame(180, -60, 160, 100, angle=25.0, pad=0.1, label="start pose")
    _place_marker((-100, 80))
    canvas.reset_view()
    canvas.set_origin("center")
    canvas.pan_to(180, -60)
    canvas.zoom_to(1.7)
    canvas.rotate_to(25)
    _start(canvas.reset_view(time=1.0, ease="ease_in_out"))
    _set_tip("Expect: gold identity under center; zoom=1 rot=0; rest=look")


def _apply():
    global _mode_i
    _cancel_handles()
    _clear()
    label, fn = MODES[_mode_i]
    hud.title = f"Timed camera — [{_mode_i + 1}/{len(MODES)}]  {label}"
    fn()


def _replay():
    label, fn = MODES[_mode_i]
    _cancel_handles()
    for o in list(_owned):
        try:
            o.destroy()
        except Exception:
            pass
    _owned.clear()
    canvas.background.clear()
    canvas.background.base = Color(0.06, 0.07, 0.10)
    canvas.reset_view()
    canvas.set_origin("center")
    hud.title = f"Timed camera — [{_mode_i + 1}/{len(MODES)}]  {label}"
    fn()


def setup(canvas):
    _apply()


def update(dt):
    global _mode_i, _tip
    if keyp.once("A"):
        _mode_i = (_mode_i - 1) % len(MODES)
        _apply()
    if keyp.once("S"):
        _mode_i = (_mode_i + 1) % len(MODES)
        _apply()
    if keyp.once("SPACE"):
        _replay()
    if keyp.once("R"):
        _cancel_handles()
        canvas.reset_view()
        canvas.set_origin("center")
        _set_tip("snap reset_view (instant)")

    running = sum(1 for h in _handles if h is not None and not h.done and not h.cancelled)
    hud.status = _tip
    live = (
        f"z={canvas.zoom:.2f}  look=({canvas.pan_x:.0f},{canvas.pan_y:.0f})  "
        f"rot={canvas.rotation:.1f}°  rest=({canvas.pan_rest_x:.0f},{canvas.pan_rest_y:.0f})"
    )
    if running:
        live += f"  · {running} tween(s)"
    hud.aux = live


run()
