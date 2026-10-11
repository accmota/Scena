"""
UI and reactive.py — smoke: widgets + @= / @when / @on_change / unlink.

Left column: one of each widget driving shapes, plus ui.font / ui.scale.
Right: linked pair (A drives B); U unlinks; arrows nudge A.

TextInput: labels sharing the Slider label column, max_length (Name, 8),
on_submit (Console: "gold", "radius 120", "nudge", "clear"; it keeps focus via
focus()), Tab / Shift+Tab between boxes, N focuses Name, Esc cancels, long
text scrolls, selection / clipboard. While a box has focus, typing keys stay
in it (Q / W / U / arrows do nothing in the game). Cmd/Ctrl+S and F5 still
reach the game, and first apply what you typed — like Enter, but the box keeps
focus and on_submit does not run (the status shows the applied values).

enabled: "Enable controls" greys out Radius, Color and Nudge (hover the
disabled Nudge button: on_hover still fires). Difficulty (bottom left) sits
near the bottom edge, so its list opens upward.

ui.scale / ui.font are construct-time — the widget column rebuilds on change.
Scale uses Q/W (not a slider) so the control is not resizing under the pointer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import skia

from scena import *
from scena.orchestration import ScenaFramework

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — reactive")
canvas.background = (0.08, 0.09, 0.12, 1)

PRIMARY = "CMD" if sys.platform == "darwin" else "CTRL"

hud = SmokeHud(
    title="Reactive + widgets",
    expect=("Widgets drive shapes; labels line up; Difficulty opens upward; "
            "disabled controls fade; typing in a box never moves A"),
    keys=(f"N focus Name  ·  Tab / Shift+Tab boxes  ·  Enter / Esc  ·  {PRIMARY}+S, F5 pass while typing  ·  "
          "Q/W ui.scale  ·  U unlink  ·  arrows nudge A"),
    status="ready",
    show_aux=True,
)

# --- state -------------------------------------------------------------------
st.create("radius", initial=70.0)
st.create("rect_w", initial=180.0)
st.create("color_name", initial="cyan")
st.create("show_square", initial=True)
st.create("nudge", initial=0.0)
st.create("alarm", initial=0.0)
st.create("ui_font", initial="(default)")
st.create("player", initial="")
st.create("controls_on", initial=True)
st.create("difficulty", initial="normal")

_FONT_WANTED = (
    "Menlo",
    "Monaco",
    "Helvetica",
    "Helvetica Neue",
    "Arial",
    "Lucida Grande",
    "Inter",
    "Segoe UI",
    "Consolas",
    "Courier New",
    "DejaVu Sans",
    "Ubuntu",
    "Cantarell",
    "Noto Sans",
    "Liberation Sans",
)
_mgr = skia.FontMgr.RefDefault()
_installed = {
    _mgr.getFamilyName(i).lower(): _mgr.getFamilyName(i)
    for i in range(_mgr.countFamilies())
}
_FONT_OPTIONS = ["(default)"] + [
    _installed[name.lower()]
    for name in _FONT_WANTED
    if name.lower() in _installed
]

_widgets: list = []
_refs: dict = {}   # current widgets the handlers talk to (rebuilt with the column)
_building = False
_SCALE_LO = 0.5
_SCALE_HI = 2.0
_SCALE_STEP = 0.1


def _wm():
    return ScenaFramework.get_instance().widget_manager


def _resolved_face() -> str:
    _wm().widget_theme._ensure()
    return _wm().widget_theme.typeface.getFamilyName()


def _chrome_aux() -> str:
    req = str(st.ui_font)
    typing = next((w.label for w in _widgets
                   if isinstance(w, TextInput) and w.focused), None)
    focus = f"  ·  typing in: {typing}" if typing else ""
    return f"ui.scale={ui.scale:.2f}  ui.font={req}  face={_resolved_face()}{focus}"


def _apply_font() -> None:
    name = str(st.ui_font)
    ui.font = None if name == "(default)" else name


def _clear_widgets() -> None:
    wm = _wm()
    for w in _widgets:
        if hasattr(w, "destroy") and getattr(w, "is_alive", True):
            w.destroy()
        else:
            wm.remove_widget(w)
    _widgets.clear()
    ui.stack_from(hud._aux)


def _w(widget):
    _widgets.append(widget)
    return widget


def _on_nudge():
    st.nudge = float(st.nudge) + 25.0
    hud.status = f"nudge → {st.nudge:.0f}"


def _nudge_hover():
    if not _refs["nudge"].enabled:
        hud.status = "Nudge is disabled — tick 'Enable controls' (hover still fires)"


_COLORS = ["cyan", "magenta", "gold", "lime", "orange"]


def _run_command(cmd):
    """Console on_submit: runs on Enter, even for the same text twice."""
    words = str(cmd).split()
    if not words:
        hud.status = "console: empty"
    elif words[0] in _COLORS:
        st.color_name = words[0]
        hud.status = f"console: color {words[0]}"
    elif words[0] == "radius" and len(words) == 2:
        try:
            st.radius = max(20.0, min(160.0, float(words[1])))
            hud.status = f"console: radius {st.radius:.0f}"
        except ValueError:
            hud.status = f"console: not a number: {words[1]!r}"
    elif words[0] == "nudge":
        _on_nudge()
    elif words[0] == "clear":
        st.nudge = 0.0
        hud.status = "console: nudge cleared"
    else:
        hud.status = f"console: unknown {cmd!r} (try gold / radius 120 / nudge / clear)"
    # Enter drops focus; a console takes it back to keep typing.
    console = _refs["console"]
    console.text = ""
    console.focus()


def _set_controls(on: bool) -> None:
    for key in ("radius", "color", "nudge"):
        _refs[key].enabled = on


def _build_widgets() -> None:
    global _building
    _building = True
    try:
        _apply_font()
        _clear_widgets()
        ui.gap()
        ui.gap()
        ui.gap()
        ui.gap()
        # No explicit width/height/size — those would hide ui.scale.
        _w(DropDown(st["ui_font"], options=_FONT_OPTIONS))
        _w(Text(text="glyphs: ← → ★ α"))
        on = bool(st.controls_on)
        # Labeled Slider + TextInputs stacked in one run share a label column.
        _refs["radius"] = _w(Slider(st["radius"], label="Radius", show_value=True,
                                    min_value=20.0, max_value=160.0, enabled=on))
        _w(TextInput(st["rect_w"], label="Rect width", placeholder="rect width"))
        _refs["name"] = _w(TextInput(st["player"], label="Name", max_length=8,
                                     placeholder="max 8 chars"))
        _refs["console"] = _w(TextInput(label="Console", placeholder="gold / radius 120",
                                        on_submit=_run_command))
        _refs["color"] = _w(DropDown(st["color_name"], options=_COLORS, enabled=on))
        _w(CheckBox(st["show_square"], label="Show square"))
        _w(CheckBox(st["controls_on"], label="Enable controls"))
        _refs["nudge"] = _w(Button(label="Nudge circle +25x", on_click=_on_nudge, enabled=on))
        _refs["nudge"].on_hover = _nudge_hover
        _w(Slider(st["alarm"], label="alarm (@when ≥ 80)", show_value=True, min_value=0.0, max_value=100.0))
        # Near the bottom edge: no room below, so the list opens upward.
        _w(DropDown(st["difficulty"], top_left=(40, 60),
                    options=["story", "easy", "normal", "hard", "brutal", "nightmare"]))
        hud.aux = _chrome_aux()
    finally:
        _building = False


# --- shapes ------------------------------------------------------------------
cx, cy = 780.0, 480.0

ball = Circle(center=(cx, cy), radius=70).set_color("cyan")
ball["radius"] @= st["radius"]
ball.center["x"] @= lambda: cx + float(st.nudge)

panel = Rect(center=(cx + 260, cy), width=180, height=120).set_color("cyan")
panel["width"] @= st["rect_w"]

sq = Square(center=(cx + 260, cy - 180), length=90).set_color("gold")

alarm_lamp = Circle(center=(cx - 160, cy - 160), radius=36).set_color("gray")

link_a = Circle(center=(cx + 40, cy - 160), radius=24).set_color("sky blue")
link_b = Circle(center=(cx + 120, cy - 160), radius=24).set_color("orange")
link_b.center["x"] @= lambda: float(link_a.center.x) + 80.0
link_b.center["y"] @= lambda: float(link_a.center.y)
(_t := (Line(p1=lambda: link_a.center, p2=lambda: link_b.center).set_color("white"))).line_width = 1


@on_change(st["ui_font"])
def _font_changed(name):
    if _building:
        return
    _build_widgets()
    hud.status = f"ui.font → {name}  face={_resolved_face()}"


@on_change(st["color_name"])
def _recolor(name):
    ball.set_color(str(name))
    panel.set_color(str(name))
    hud.status = f"color → {name}"


@on_change(st["show_square"])
def _toggle_sq(show):
    sq.visible = bool(show)
    hud.status = f"square visible → {bool(show)}"


@on_change(st["radius"])
def _radius_status(r):
    hud.status = f"radius → {float(r):.1f}"


@on_change(st["rect_w"])
def _width_status(w):
    hud.status = f"rect width → {float(w):.1f}"


@on_change(st["player"])
def _player_status(name):
    hud.status = f"name committed → {name!r} (max_length 8)"


@on_change(st["controls_on"])
def _controls_status(on):
    _set_controls(bool(on))
    hud.status = f"controls enabled → {bool(on)} (Radius, Color, Nudge)"


@on_change(st["difficulty"])
def _difficulty_status(level):
    hud.status = f"difficulty → {level}"


@when(lambda: float(st.alarm) >= 80.0)
def _alarm_on():
    alarm_lamp.set_color("red")
    hud.status = "when: alarm ≥ 80"


@when(lambda: float(st.alarm) < 80.0)
def _alarm_off():
    alarm_lamp.set_color("gray")


def _nudge_scale(delta: float) -> None:
    ui.scale = min(_SCALE_HI, max(_SCALE_LO, round(ui.scale + delta, 2)))
    _build_widgets()
    hud.status = f"ui.scale → {ui.scale:.2f}"


_build_widgets()


def update(dt):
    hud.aux = _chrome_aux()
    # These reach the game even while a box has focus. The box applies what
    # was typed first (like Enter, but it keeps focus), so the values are current.
    if keyp.once(f"{PRIMARY}+S"):
        hud.status = f"{PRIMARY}+S reached the game · rect width = {float(st.rect_w):.1f}, name = {str(st.player)!r}"
    if keyp.once("F5"):
        hud.status = "F5 reached the game"
    # Plain keys only arrive when no box has focus (a focused box claims them).
    if keyp.once("N"):
        _refs["name"].focus()
        hud.status = "Name focused (text selected) — type, Tab to move on"
    if keyp.once("Q"):
        _nudge_scale(-_SCALE_STEP)
    if keyp.once("W"):
        _nudge_scale(_SCALE_STEP)
    if keyp.once("U"):
        link_b.center["x"].unlink()
        link_b.center["y"].unlink()
        hud.status = "unlinked B from A — B should stop following"
        hud.expect = "B no longer follows A"
    if keyp("LEFT"):
        link_a.move_by(-140 * dt, 0)
    if keyp("RIGHT"):
        link_a.move_by(140 * dt, 0)


run()
