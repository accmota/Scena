"""
text.py — smoke: Text paint catalog + ui/world placement.

Question
--------
Does ``Text`` paint and place like a Graphic caption?

Pages (A/S)
-----------
  Solid · Background · Fill · Line · Place · Align · Glow

Pan: ui pages stay; world pages move. Fail buttons show errors on status.

Usage
-----
    python scripts/smoke/text.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud, apply_camera

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — Text")
canvas.background = "navy"
Stars(pan_response=1)
Clouds(pan_response=1)

st.create("align_n", initial=1)

hud = SmokeHud(
    title="Text",
    expect="Paint · place · align/width; pan to compare ui vs world",
    keys="A/S page  ·  arrows pan  ·  Shift rotate/zoom",
    status="…",
)

_owned: list = []
_page_i = 0
_PAGES = ("Solid", "Background", "Fill", "Line", "Place", "Align", "Glow")
_align_tick = 0.0


Text("Multiline Text\nTESTE ABC ABC\nAAABBBCCC DDD EEE\nAJI ASIJWEU", top_left=(50, 126), font_size=16, color="white")  # grows down to y≈50

def _track(obj):
    _owned.append(obj)
    return obj


def _clear():
    for o in list(_owned):
        try:
            o.destroy()
        except Exception:
            pass
    _owned.clear()


def _cap(msg: str, x: float, y: float, **kw):
    _track(Text(msg, top_left=(x, y + 17), font_size=14, color=Color(0.65, 0.7, 0.8, 1), **kw))


def _show_exc(exc: BaseException) -> None:
    msg = f"{type(exc).__name__}: {exc}"
    if len(msg) > 140:
        msg = msg[:137] + "…"
    hud.status = msg


def _fail_neon():
    try:
        Text("x", top_left=(40, 215), visual=Neon())
        hud.status = "UNEXPECTED: Neon on Text"
    except Exception as e:
        _show_exc(e)


def _fail_cheap():
    try:
        t = Text("x", top_left=(40, 215))
        t.visual = CheapGlow()
        hud.status = "UNEXPECTED: CheapGlow on Text"
    except Exception as e:
        _show_exc(e)


def _fail_world_xy():
    try:
        Text("x", center=(100, 100), top_left=(20, 20))
        hud.status = "UNEXPECTED: center+top_left"
    except Exception as e:
        _show_exc(e)


def _fail_ui_collide():
    t = _track(Text("x", top_left=(40, 235)))
    try:
        t.collidable = True
        hud.status = "UNEXPECTED: collidable on ui Text"
    except Exception as e:
        _show_exc(e)


def _fail_two_anchors():
    try:
        Text("x", top_left=(100, 100), top_right=(200, 100))
        hud.status = "UNEXPECTED: two anchors"
    except Exception as e:
        _show_exc(e)


_btn_y = H - 155
for i, (lab, fn) in enumerate(
    (
        ("visual=Neon", _fail_neon),
        ("visual=CheapGlow", _fail_cheap),
        ("center+top_left", _fail_world_xy),
        ("ui collidable", _fail_ui_collide),
        ("two anchors", _fail_two_anchors),
    )
):
    Button(label=lab, top_left=(24 + i * 200, _btn_y + 28), width=190, on_click=fn)


def _page_solid():
    _cap("color= / set_color solid (fill only; add .line for outline)", 40, H - 220)
    a = _track(Text("SOLID WHITE", top_left=(80, 553), font_size=28, color="white"))
    b = _track(Text("set_color tomato", top_left=(80, 493), font_size=28))
    b.set_color("tomato")
    # Outline is explicit — color= does not invent a contrast stroke.
    c = _track(Text("fill + line", top_left=(80, 433), font_size=28, color="tomato"))
    c.line = Color(1, 1, 1, 1)
    c.line_width = 1.5


def _page_background():
    _cap("background= plate vs unboxed", 40, H - 220)
    _track(Text("UNBOXED", top_left=(80, 551), font_size=26, color="gold"))
    _track(
        Text(
            "BOXED PLATE",
            top_left=(80, 481),
            font_size=26,
            color="white",
            background=Color(0.15, 0.05, 0.25, 0.92),
        )
    )


def _page_fill():
    _cap(".fill solid and Gradient", 40, H - 220)
    a = _track(Text("FILL SOLID", top_left=(80, 553), font_size=28))
    a.fill = Color(0.3, 0.85, 1.0, 1)
    b = _track(Text("FILL GRADIENT", top_left=(80, 483), font_size=28))
    b.fill = Gradient("blue", "red", type="linear", angle=0)


def _page_line():
    _cap(".line + line_width (+ Gradient outline)", 40, H - 220)
    a = _track(Text("OUTLINE", top_left=(80, 562), font_size=36, color=(0.1, 0.1, 0.12, 1)))
    a.line = Color(1, 0.9, 0.2, 1)
    a.line_width = 1.5
    b = _track(Text("GRAD STROKE", top_left=(80, 482), font_size=36, color=(0.05, 0.05, 0.08, 1)))
    b.line = Gradient("red", "yellow", type="linear", angle=90)
    b.line_width = 3.0


def _page_place():
    _cap("auto-stack · top_left= ui · center= world · layer top", 40, H - 220)
    # Start the demo column under the section caption (the default origin is
    # inside the smoke HUD band).
    ui.stack_origin(40, H - 250)
    _track(Text("STACK A"))
    _track(Text("STACK B"))
    _track(Text("explicit ui", top_left=(400, 506), font_size=22, color="cyan"))
    ship = _track(Circle(center=(900, 420), radius=28).set_color("orange"))
    _track(Text("HP", center=ship.center, font_size=22, color="white"))
    _track(Text("ON TOP", center=(900, 520), layer="top", font_size=20, color="lime"))
    _cap("pan: stacked/top_left stay; HP + ON TOP move with world", 40, 120)


def _guide(x: float, y0: float, y1: float):
    _track(Line(
        p1=(x, y0), p2=(x, y1),
        color=Color(0.4, 0.5, 0.65, 0.55),
        layer="ui",
    ))


def _page_align():
    _cap(
        "anchor pin (live counter) · width= fixed plate · world nameplate",
        40,
        H - 220,
    )
    st.align_n = 1
    # Three HUD anchors: top_left / top_center / top_right — counter grows; pin stays.
    pins = ((220, "top_left"), (700, "top_center"), (1180, "top_right"))
    for x, anchor in pins:
        _guide(x, 560, 480)
        _cap(f"{anchor}=", x - 40 if anchor != "top_right" else x - 100, 570)
        t = _track(Text("", font_size=28, color="cyan", **{anchor: (x, 533)}))
        t["text"] @= lambda: f"{st.align_n}"

    # Fixed width: short vs overflow; plate stays put.
    _cap("width=200 plate (short + overflow clip)", 40, 420)
    plate_bg = Color(0.12, 0.08, 0.2, 0.9)
    _track(Text(
        "Hi",
        top_left=(80, 388),
        font_size=24,
        width=200,
        align="left",
        color="white",
        background=plate_bg,
    ))
    _track(Text(
        "OVERFLOW CLIPPED HERE",
        top_left=(320, 388),
        font_size=24,
        width=200,
        align="left",
        color="gold",
        background=plate_bg,
    ))
    _track(Text(
        "RIGHT IN BOX",
        top_left=(850, 388),
        font_size=24,
        width=200,
        align="right",
        color="white",
        background=plate_bg,
    ))

    ship = _track(Circle(center=(1100, 280), radius=32).set_color("orange"))
    _track(Text(
        "HP 100/100",
        center=ship.center,
        font_size=20,
        width=110,
        align="center",
        color="white",
        background=Color(0.05, 0.05, 0.1, 0.85),
    ))
    _cap("world nameplate: center= + width= (pose stable)", 900, 200)


def _page_glow():
    _cap("glow=Glow / CheapGlow / True — captions share the same halo", 40, H - 220)
    t = _track(Text("GLOW HUD", top_left=(80, 522), font_size=36, color="cyan"))
    t.glow = CheapGlow()
    w = _track(Text("GLOW WORLD", center=(800, 420), font_size=36, color="gold"))
    w.glow = True


def _rebuild():
    global _align_tick
    _clear()
    _align_tick = 0.0
    name = _PAGES[_page_i]
    {
        "Solid": _page_solid,
        "Background": _page_background,
        "Fill": _page_fill,
        "Line": _page_line,
        "Place": _page_place,
        "Align": _page_align,
        "Glow": _page_glow,
    }[name]()
    hud.status = f"page: {name}"


def on_key_down(key):
    global _page_i
    if key == "A":
        _page_i = (_page_i - 1) % len(_PAGES)
        _rebuild()
    elif key == "S":
        _page_i = (_page_i + 1) % len(_PAGES)
        _rebuild()


def update(dt):
    global _align_tick
    apply_camera(dt, about=(W * 0.5, H * 0.5))
    if _PAGES[_page_i] == "Align":
        _align_tick += dt
        if _align_tick >= 0.35:
            _align_tick = 0.0
            st.align_n = int(st.align_n) + 1


_rebuild()
run()
