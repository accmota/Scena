"""
ui_layer.py — smoke: reserved ``ui`` view layer vs world layers.

Question
--------
Does ``ui`` stay view-locked and refuse world-only features, while
``default`` / ``top`` do not?

Pages (A/S)
-----------
  Shapes · Sprites

Each page: left = ``layer="ui"``; right = world ``default``. Pan the camera —
HUD side stays fixed; world side moves. Click/drag both.

Fail buttons (caught): collidable / @collide / SpatialFx / set_post_fx /
delete on ``ui``. Status shows the exception. Crash = uncaught delete.

Usage
-----
    python scripts/smoke/ui_layer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud, apply_camera

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — ui layer")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="UI layer",
    expect="Left = ui (view-locked) · right = world (pans) · fail buttons show errors",
    keys="A/S page  ·  arrows pan  ·  Shift+←/→ rotate  ·  Shift+↑/↓ zoom  ·  drag both",
    status="pan to confirm ui stays fixed…",
)

_owned: list = []
_page_i = 0
_PAGES = ("Shapes", "Sprites", "Text")
_bloom = None


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


def _cap(text: str, x: float, y: float, *, size: int = 14, color=None) -> None:
    lb = Text(
        text=text,
        top_left=(x, y + 15),
        font_size=size,
        color=color or Color(0.7, 0.75, 0.85, 1),
    )
    _owned.append(lb)


def _show_exc(exc: BaseException) -> None:
    msg = f"{type(exc).__name__}: {exc}"
    if len(msg) > 140:
        msg = msg[:137] + "…"
    hud.status = msg
    try:
        _track(
            Text(
                text=msg[:90],
                top_left=(24, H - 185),
                font_size=13,
                color=Color(1, 0.9, 0.85, 1),
                background=Color(0.55, 0.12, 0.1, 0.92),
            )
        )
    except Exception:
        pass


def _fail_collidable():
    c = _track(Circle(center=(120, 400), radius=20, layer="ui"))
    try:
        c.collidable = True
        hud.status = "UNEXPECTED: collidable succeeded on ui"
    except Exception as e:
        _show_exc(e)


def _fail_collide():
    a = _track(Circle(center=(120, 360), radius=18, layer="ui", group="ui_fail"))
    b = _track(Circle(center=(200, 360), radius=18, group="world_fail"))
    try:

        @collide(a, b)
        def _on(me, other, info):
            pass

        hud.status = "UNEXPECTED: @collide with ui succeeded"
    except Exception as e:
        _show_exc(e)


def _fail_spatial():
    try:
        Fire(center=(120, 440), layer="ui")
        hud.status = "UNEXPECTED: Fire on ui succeeded"
    except Exception as e:
        _show_exc(e)


def _fail_post_fx():
    try:
        canvas.layers["ui"].post_fx = False
        hud.status = "UNEXPECTED: set_post_fx(ui) succeeded"
    except Exception as e:
        _show_exc(e)


def _fail_delete():
    try:
        canvas.layers["ui"].delete()
        hud.status = "UNEXPECTED: delete(ui) succeeded"
    except Exception as e:
        _show_exc(e)


def _crash_delete():
    hud.status = "deleting ui with no try/except…"
    canvas.layers["ui"].delete()  # uncaught — script dies


# Fail-button strip (view space; below SmokeHud chrome)
_btn_y = H - 155
for i, (lab, fn) in enumerate(
    (
        ("collidable=True", _fail_collidable),
        ("@collide ui", _fail_collide),
        ("SpatialFx ui", _fail_spatial),
        ("set_post_fx ui", _fail_post_fx),
        ("delete ui", _fail_delete),
        ("Crash: delete ui", _crash_delete),
    )
):
    Button(
        label=lab,
        top_left=(24 + (i % 3) * 200, _btn_y - (i // 3) * 40 + 28),
        width=190,
        on_click=fn,
    )


Button(
    label="Toggle Bloom (ui sharp?)",
    top_left=(W - 280, H - 127),
    width=250,
    on_click=lambda: _toggle_bloom(),
)


def _toggle_bloom():
    global _bloom
    if _bloom is None:
        try:
            _bloom = Bloom()
            hud.status = "Bloom on — ui should stay sharp above post"
        except Exception as e:
            _show_exc(e)
            _bloom = None
    else:
        try:
            _bloom.remove()
        except Exception:
            pass
        _bloom = None
        hud.status = "Bloom off"


def _page_shapes():
    _cap("ui (view)", 80, H - 280, size=16, color=Color(0.4, 0.9, 1, 1))
    _cap("world default", 720, H - 280, size=16, color=Color(1, 0.75, 0.35, 1))

    ui_c = _track(Circle(center=(200, 480), radius=45, layer="ui").set_color("cyan"))
    ui_c.draggable = True
    ui_r = _track(
        Rect(center=(200, 360), width=90, height=55, layer="ui").set_color("sky blue")
    )
    ui_r.draggable = True

    w_c = _track(Circle(center=(840, 480), radius=45).set_color("orange"))
    w_c.draggable = True
    w_r = _track(Rect(center=(840, 360), width=90, height=55).set_color("gold"))
    w_r.draggable = True

    _cap("pan: left stays, right moves · drag either", 80, 120, size=13)


def _page_sprites():
    _cap("ui Sprite", 80, H - 280, size=16, color=Color(0.4, 0.9, 1, 1))
    _cap("world Sprite", 720, H - 280, size=16, color=Color(1, 0.75, 0.35, 1))
    # Missing asset → checker placeholder; still proves layer space.
    ui_s = _track(Sprite("missing_ui.png", center=(200, 420), layer="ui", width=90, height=90))
    ui_s.draggable = True
    w_s = _track(Sprite("missing_world.png", center=(840, 420), width=90, height=90))
    w_s.draggable = True
    _cap("same as Shapes page for sprites", 80, 120, size=13)


def _page_text():
    _cap("ui Text (stacked / x1)", 80, H - 280, size=16, color=Color(0.4, 0.9, 1, 1))
    _cap("world Text (center=)", 720, H - 280, size=16, color=Color(1, 0.75, 0.35, 1))
    _track(Text("HUD SCORE", top_left=(120, 513), font_size=28, color="cyan"))
    ship = _track(Circle(center=(840, 420), radius=30).set_color("orange"))
    _track(Text("HP", center=ship.center, font_size=28, color="white"))
    _cap("pan: left stays · right moves with ship", 80, 120, size=13)


def _rebuild():
    _clear()
    name = _PAGES[_page_i]
    if name == "Shapes":
        _page_shapes()
    elif name == "Sprites":
        _page_sprites()
    else:
        _page_text()
    hud.status = f"page: {name} — pan to compare ui vs world"


def on_key_down(key):
    global _page_i
    if key == "A":
        _page_i = (_page_i - 1) % len(_PAGES)
        _rebuild()
    elif key == "S":
        _page_i = (_page_i + 1) % len(_PAGES)
        _rebuild()


def update(dt):
    apply_camera(dt, about=(W * 0.5, H * 0.5))


_rebuild()
run()
