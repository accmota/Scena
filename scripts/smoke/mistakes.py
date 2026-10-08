"""
mistakes.py — smoke: author construct mistakes stay legal or fail clearly.

Question
--------
Do author construct mistakes stay legal (checker + warn) or fail clearly
(TypeError Label), without freezing the catalog?

Pages (A/S)
-----------
  Sprite · Svg · Texture · Shape · Color

Each page: top row = valid actor; bottom row = matching mistake.
Asset mistakes place a real actor (magenta/yellow checker). Kwargs mistakes
are ``try/except TypeError`` at setup — cell is a Text, never constructed
from ``on_update``.

The **Crash** button constructs ``Circle(aaa=1)`` with no try/except so you
can confirm an uncaught author TypeError stops the script.

Usage
-----
    python scripts/smoke/mistakes.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — author mistakes")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="Author mistakes",
    expect="Top = valid · bottom = mistake (checker or raised TypeError Label)",
    keys="A/S page  ·  Crash button = uncaught TypeError (stops script)  ·  status = last warn",
    status="no warning",
)

# Persistent: not cleared on A/S. Uncaught construct — proves the script stops
# without try/except (unlike the tomato Labels on each page).
def _crash_invalid_shape():
    hud.status = "constructing Circle(aaa=1) with no try/except…"
    Circle(aaa=1)  # TypeError — not caught; run() dies


Button(
    label="Crash: invalid Circle (no try/except)",
    top_left=(24, 84),
    width=360,
    on_click=_crash_invalid_shape,
)

_owned: list = []
_page_i = 0
_last_warn = "no warning"
_PAGES = ("Sprite", "Svg", "Texture", "Shape", "Color")

# Capture RuntimeWarnings for the status line (Sprite / Texture / Color).
_warn_log: list[str] = []


def _showwarning(message, category, filename, lineno, file=None, line=None):
    text = str(message).split("\n", 1)[0]
    low = text.lower()
    if (
        issubclass(category, Warning)
        and (
            "scena error" in low
            or "failed" in low
            or "missing" in low
            or "unknown color" in low
            or "placeholder" in low
            or "checker" in low
            or "svg expected" in low
        )
    ):
        _warn_log.append(text[:120])
    return _orig_showwarning(message, category, filename, lineno, file=file, line=line)


_orig_showwarning = warnings.showwarning
warnings.showwarning = _showwarning


def _cap(text: str, x: float, y: float, *, size: int = 14) -> None:
    lb = Text(text=text, top_left=(x, y + 15), font_size=size, color=Color(0.7, 0.75, 0.85, 1))
    _owned.append(lb)


def _track(obj):
    _owned.append(obj)
    return obj


def _clear():
    for o in list(_owned):
        try:
            if hasattr(o, "destroy") and getattr(o, "is_alive", True):
                o.destroy()
            elif hasattr(o, "clean_up"):
                o._widget_manager.remove_widget(o)
                o._clean_up()
        except Exception:
            pass
    _owned.clear()


def _kwargs_cell(exc: BaseException, x: float, y: float) -> None:
    msg = f"raised {type(exc).__name__}: {exc}"
    if len(msg) > 64:
        msg = msg[:61] + "…"
    _track(Text(text=msg, top_left=(x - 40, y + 15), font_size=13, color=Color("tomato")))


def _page_sprite():
    _cap("valid Sprite (atlas frame)", 80, H - 160)
    try:
        sheet = Sheet("../../examples/media/shooter/sheet.xml")
        _track(Sprite(source=sheet, frame="playerShip1_blue.png", height=64, center=(220, 520)))
    except Exception as e:
        _kwargs_cell(e, 180, 520)

    _cap("missing atlas → checker + warn", 80, 360)
    _track(Sprite(Sheet("no_such_sheet.xml"), frame="x.png", height=64, center=(220, 220)))

    _cap("unknown kwargs → TypeError (Label)", 520, H - 160)
    try:
        Sprite(center=(700, 520), aaa=1)
    except TypeError as e:
        _kwargs_cell(e, 640, 520)

    _cap("unknown frame → checker + warn", 520, 360)
    try:
        sheet = Sheet("../../examples/media/shooter/sheet.xml")
        _track(Sprite(source=sheet, frame="not_a_real_frame.png", height=64, center=(700, 220)))
    except Exception as e:
        _kwargs_cell(e, 640, 220)


def _page_svg():
    _cap("valid Svg (filename)", 80, H - 160)
    _track(Svg("sonnenschirm.svg", height=80, center=(220, 520)))   # next to this script

    _cap("missing Svg → placeholder + warn", 80, 360)
    _track(Svg("no_such_icon.svg", height=80, center=(220, 220)))


def _page_texture():
    _cap("valid Texture fill", 80, H - 160)
    c = _track(Circle(center=(220, 520), radius=48))
    try:
        c.fill = Texture("../../examples/media/space/playerShip1_red.png")
    except Exception:
        c.set_color("cyan")

    _cap("missing Texture → yellow checker + warn", 80, 360)
    bad = _track(Circle(center=(220, 220), radius=48))
    bad.fill = Texture("no_such_texture.png")


def _page_shape():
    _cap("valid Circle(center=) home fill", 80, H - 160)
    _track(Circle(center=(220, 520)).set_color("lime"))

    _cap("Circle(aaa=1) → TypeError Label", 80, 360)
    try:
        Circle(aaa=1)
    except TypeError as e:
        _kwargs_cell(e, 180, 220)

    _cap("valid Rect + .glow stamp", 520, H - 160)
    good = _track(Rect(center=(700, 520), width=80, height=50).set_color("gold"))
    good.glow = Glow()

    _cap("visual=Glow() → TypeError (stamp hint)", 520, 360)
    try:
        bad = Circle(center=(700, 220), radius=28).set_color("cyan")
        bad.visual = Glow()
    except TypeError as e:
        _kwargs_cell(e, 640, 220)

    _cap("Line(p1=) → ValueError (incomplete)", 980, 360)
    try:
        Line(p1=(0, 0))
    except ValueError as e:
        _kwargs_cell(e, 1060, 220)


def _page_color():
    _cap("valid Color name", 80, H - 160)
    _track(Circle(center=(220, 520), radius=40).set_color("tomato"))

    _cap("unknown Color name → warn + magenta", 80, 360)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        c = Color("not_a_real_color_xyz")
        for w in caught:
            _warn_log.append(str(w.message).split("\n", 1)[0][:120])
    _track(Circle(center=(220, 220), radius=40, color=c))


_BUILD = {
    "Sprite": _page_sprite,
    "Svg": _page_svg,
    "Texture": _page_texture,
    "Shape": _page_shape,
    "Color": _page_color,
}


def _rebuild():
    global _last_warn
    _clear()
    name = _PAGES[_page_i]
    hud.title = f"Author mistakes — {name} ({_page_i + 1}/{len(_PAGES)})"
    before = len(_warn_log)
    _BUILD[name]()
    if len(_warn_log) > before:
        _last_warn = _warn_log[-1]
    hud.status = f"warn: {_last_warn}"
    hud.expect = (
        "Top valid · bottom mistake — catalog keeps paging; no freeze"
    )


def setup(c):
    _rebuild()


def update(dt, c):
    global _page_i, _last_warn
    if keyp.once("A"):
        _page_i = (_page_i - 1) % len(_PAGES)
        _rebuild()
    if keyp.once("S"):
        _page_i = (_page_i + 1) % len(_PAGES)
        _rebuild()
    if _warn_log:
        _last_warn = _warn_log[-1]
        hud.status = f"warn: {_last_warn}"


run()
