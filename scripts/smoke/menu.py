"""
menu.py — smoke the game Menu: look, pause, grid, follow, box, font, icons.

Question
--------
Does a modal menu dim the view, sit in the game view (not the HUD column),
and close on a pick — while a non-modal menu can follow a hero?

Pages are keys, not A/S. One menu at a time except a modal over the follower.

Controls
--------
  1  title menu (modal)
  2  pause menu (modal, pause=True) — also Escape
  3  level grid (modal, cols=3)
  4  non-modal menu following the hero (center=lambda)
  5  box= fit (font shrinks)
  6  font file + icons

Usage
-----
    python scripts/smoke/menu.py
"""
from __future__ import annotations

from pathlib import Path

import skia

from scena import *

ROOT = Path(__file__).resolve().parents[2]
FONT = str(ROOT / "examples" / "media" / "space" / "kenvector_future.ttf")
ICON_DIR = Path(__file__).resolve().parent / "_menu_icons"


def _icon(name, rgb):
    ICON_DIR.mkdir(exist_ok=True)
    path = ICON_DIR / name
    if path.is_file():
        return str(path)
    info = skia.ImageInfo.Make(32, 32, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surface = skia.Surface.MakeRaster(info)
    surface.getCanvas().clear(skia.ColorSetRGB(*rgb))
    surface.makeImageSnapshot().save(str(path), skia.kPNG)
    return str(path)


W, H = 1000, 700
init(width=W, height=H, window_scale=0.75, title="Smoke — menu")
canvas.background = (0.08, 0.1, 0.16, 1)

hero = Circle(center=(180, 160), radius=28, color="tomato")
st.msg = "1 título  2/Esc pausa  3 fases  4 seguir  5 caixa  6 fonte+ícones"
status = Text("", top_left=(24, 57), font_size=18, color="white")
status["text"] @= lambda: st.msg


def _note(opcao):
    st.msg = f"escolheu {opcao!r}"


def titulo():
    Menu(
        options=["Jogar", "Fases", "Sair"],
        title="Scena abcjiowjejoi \n asdjsadioas!",
        on_choose=_note,
        font_size=32,
    )


def pausa():
    Menu(
        options=["Continuar", "Título"],
        title="Pausa Pausa Pausa Pausa",
        font_size=16,
        pause=True,
        on_choose=_note,
    )


def fases():
    Menu(
        options=range(1, 8),
        title="Fase",
        cols=3,
        on_choose=_note,
        background=Gradient("red", "yellow"),
    )


def seguir():
    Menu(
        options=["Perto", "Longe"],
        modal=False,
        center=lambda: (hero.center.x, hero.center.y + 90),
        on_choose=_note,
    )


def caixa():
    region = Box(center=(W * 0.5, H * 0.55), width=220, height=140)
    Rect(
        center=region.center,
        width=region.width,
        height=region.height,
        layer="ui",
        color=(1, 1, 1, 0.15),
    )
    Menu(
        options=["Uma opção bem comprida", "Outra também"],
        box=region,
        font_size=48,
        background="dark blue",
        color="white",
        on_choose=_note,
    )


def fonte():
    Menu(
        options=["Azul", "Vermelha"],
        title="Nave",
        font=FONT,
        font_size=36,
        color="white",
        background="black",
        icons=[
            _icon("azul.png", (40, 120, 255)),
            _icon("vermelha.png", (220, 50, 60)),
        ],
        on_choose=_note,
    )


def update(dt):
    if keyp.once("1"):
        titulo()
    if keyp.once("2") or keyp.once("ESC"):
        pausa()
    if keyp.once("3"):
        fases()
    if keyp.once("4"):
        seguir()
    if keyp.once("5"):
        caixa()
    if keyp.once("6"):
        fonte()
    if keyp("LEFT"):
        hero.center.x -= 180 * dt
    if keyp("RIGHT"):
        hero.center.x += 180 * dt
    if keyp("DOWN"):
        hero.center.y -= 180 * dt
    if keyp("UP"):
        hero.center.y += 180 * dt


run()
