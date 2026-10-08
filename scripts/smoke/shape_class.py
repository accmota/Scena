"""
shape_class.py — smoke: Shape class defaults, home fill, subclass clone.

Question
--------
Can a Shape subclass own costume + behaviour like a Sprite subclass
(``class Bolt(Circle, radius=…, color=…, group=…)``), spawn with home fill
(``Bolt(center=…)``), and ``clone()`` as the same subclass?

Pages (A/S)
-----------
  1 · Class defaults — style/group/size on the class; expert path ignores size
  2 · Home fill — empty / center= / complete home-minus-center; incomplete raises
  3 · Subclass clone — ``Flyer.clone()`` keeps type + ``on_update``; bare Circle does not

Usage
-----
    python scripts/smoke/shape_class.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — shape class form")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="Shape class form",
    expect="A/S: class defaults · home fill · subclass clone",
    keys="A/S page  ·  page 3: SPACE = extra Flyer.clone()",
    status="",
)

_owned: list = []
_page_i = 0
_PAGES: list = []


def _page(name: str, expect: str):
    def deco(fn):
        _PAGES.append((name, expect, fn))
        return fn

    return deco


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


def _err_label(exc: BaseException, x: float, y: float) -> None:
    msg = f"raised {type(exc).__name__}: {exc}"
    if len(msg) > 72:
        msg = msg[:69] + "…"
    _track(Text(text=msg, top_left=(x, y + 15), font_size=13, color=Color("tomato")))


# ---------------------------------------------------------------------------
# Module-level actor classes (always constructed — never “class only”)
# ---------------------------------------------------------------------------

class GoldBolt(Circle, radius=28, color="gold", group="bolt"):
    """(1) Class costume — spawn with center= only."""

    def on_update(self, dt):
        self.move_by(0, 80 * dt)
        if self.center.y > H - 100:
            self.center.y = 240


class Brick(Rect, width=90, height=36, color="sienna", group="brick"):
    """(1) Rect home size on the class."""

    pass


class Shot(Circle, radius=40, color="gold", group="shot"):
    """(1) Expert diameter path — class radius must NOT apply; color still gold."""

    pass


class Flyer(Circle, radius=36, color="deepskyblue", group="flyer"):
    """(3) Subclass with motion — clone must keep on_update."""

    def setup(self):
        self.hp = 1

    def on_update(self, dt):
        self.move_by(140 * dt, 0)
        if self.center.x > W - 100:
            self.center.x = 100


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@_page(
    "1 · Class defaults",
    "Gold bolts + brown bricks from class kwargs; diameter Shot is gold but radius≠40",
)
def _p_class_defaults():
    _cap("GoldBolt(center=…) — class radius=28, color=gold (rising)", 40, H - 150)
    for i, x in enumerate((160, 280, 400)):
        _track(GoldBolt(center=(x, 520 - i * 12)))

    _cap("Brick(center=…) — class width/height/color", 40, H - 400)
    for i, x in enumerate((180, 320, 460)):
        _track(Brick(center=(x, 320)))

    # Instantiated — not class-only. TWO_POINTS diameter = 100 → radius 50, not class 40.
    _cap("Shot(p1=, p2=) expert — class radius ignored; color still gold", 700, H - 150)
    d = _track(Shot(p1=(760, 650), p2=(900, 650)))



    _cap("class Bad(Rect, radius=8) → TypeError", 700, 220)
    try:
        class Bad(Rect, radius=8):  # noqa: F841
            pass
    except TypeError as e:
        _err_label(e, 700, 160)


@_page(
    "2 · Home fill",
    "Empty / center= / complete home-minus-center. Partial pairs and Line(p1=) raise.",
)
def _p_home_fill():
    from scena.shapes import _default_pose

    (cx, cy), unit = _default_pose()

    _cap(
        "LEGAL: empty · center= · Circle(radius=) · Rect(width=, height=) · Line(length=, angle=)",
        40,
        H - 145,
        size=13,
    )
    _cap(
        "ILLEGAL: Rect(width=) · Rect(center=, width=) · Line(p1=) — incomplete, ValueError",
        40,
        H - 170,
        size=13,
    )

    _cap(f"Circle(center=) → radius filled (~{unit:.0f})", 40, H - 220)
    _track(Circle(center=(200, 620)).set_color("lime"))

    _cap("Circle(radius=50) → design-space center", 500, H - 380)
    _cap(f"(≈ {cx:.0f}, {cy:.0f})", 500, H - 400)
    _track(Circle(radius=50).set_color("cyan"))

    _cap("Rect(center=, width=100, height=60) → exact size", 40, H - 420)
    r = _track(Rect(center=(220, 380), width=100, height=60).set_color("orange"))
    _cap(f"height={float(r.height):.0f}", 40, H - 450)

    _cap("Line(center=) → length/angle filled", 500, H - 220)
    ln = _track(Line(center=(620, 640)).set_color("white"))
    ln.line_width = 4
    _cap(f"length={float(ln.length):.0f}  p2=({float(ln.p2.x):.0f},{float(ln.p2.y):.0f})", 500, H - 250)

    _cap("Square(center=) → length filled", 900, H - 420)
    _track(Square(center=(1040, 360)).set_color("violet"))

    _cap("Line(p1=) incomplete → ValueError", 40, 200)
    try:
        Line(p1=(0, 0))
    except ValueError as e:
        _err_label(e, 40, 140)

    _cap("Rect(center=, width=) incomplete → ValueError", 40, 80)
    try:
        Rect(center=(0, 0), width=12)
    except ValueError as e:
        _err_label(e, 40, 20)


@_page(
    "3 · Subclass clone",
    "Three Flyers drift right (clone kept on_update). Tomato Circles stay put.",
)
def _p_clone():
    _cap("Flyer → clone → clone  (all Flyer, all fly right)", 40, H - 150)
    src = _track(Flyer(center=(160, 620)))
    a = _track(src.clone())
    a.move_to(160, 480)
    a.set_color("deepskyblue")
    b = _track(a.clone())
    b.move_to(160, 340)
    b.set_color("deepskyblue")
    _cap(
        f"types={type(src).__name__},{type(a).__name__},{type(b).__name__}  "
        f"hp={float(a.hp)}  on_update bound={callable(a.on_update)}",
        40,
        H - 420,
    )

    _cap("Circle → clone  (no on_update — stay put)", 720, H - 150)
    plain = _track(Circle(center=(900, 620), radius=36, color="tomato"))
    plain_copy = _track(plain.clone())
    plain_copy.move_to(900, 440)
    plain_copy.set_color("tomato")
    _cap(
        f"clone type={type(plain_copy).__name__}  "
        f"on_update is None={plain_copy.on_update is None}",
        720,
        H - 420,
    )

    _cap("SPACE: spawn another Flyer.clone() near the bottom", 40, 160)


def _rebuild():
    _clear()
    name, expect, fn = _PAGES[_page_i]
    hud.title = f"Shape class form — {name} ({_page_i + 1}/{len(_PAGES)})"
    hud.expect = expect
    fn()
    n = sum(1 for o in _owned if getattr(o, "is_alive", False) and not isinstance(o, Text))
    hud.status = f"{name}  ·  live actors={n}"


def setup(c):
    _rebuild()


def update(dt, c):
    global _page_i
    if keyp.once("A"):
        _page_i = (_page_i - 1) % len(_PAGES)
        _rebuild()
    if keyp.once("S"):
        _page_i = (_page_i + 1) % len(_PAGES)
        _rebuild()
    if _page_i == 2 and keyp.once("SPACE"):
        for o in _owned:
            if isinstance(o, Flyer) and o.is_alive:
                twin = _track(o.clone())
                twin.move_to(160, 180)
                twin.set_color("deepskyblue")
                hud.status = f"spawned {type(twin).__name__}.clone()  live actors+=1"
                break


run()
