"""
confine.py — smoke: Graphic.confine (clamp / bounce / wrap × by=).

Pages (A/S)
-----------
  Clamp     arrows move a ship; confine(PLAY) stops the center at the edge
  By        Q/W cycle by= center | box | overlap on a fat Rect vs a platform
  Bounce    DVD-style balls (action="bounce", needs .vel)
  Wrap      Asteroids wrap (action="wrap"); arrows thrust
  Oriented  rotated arena — local-frame sides; Angle slider; bounce
  Edge      too-big by="box" pin + confine against a Rect Graphic

Usage
-----
    python scripts/smoke/confine.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.78, title="Smoke — confine")
collision.floor = True   # gravity: bodies stand on floors (ramps, lifts, seams)
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="confine",
    expect="A/S pages — clamp · by= · bounce · wrap · oriented · edge cases",
    keys="A/S page",
    status="ready",
    show_aux=True,
)

CONTENT_X = 40.0
CONTENT_CX = W * 0.5
CONTENT_CY = 420.0

_PAGES: list = []
_owned: list = []
_page_i = 0

_mover = None
_ghost = None
_region = None
_outline = None
_balls: list = []
_by_mode = "center"
_BY_CYCLE = ("center", "box", "overlap")
_flash_edges: dict = {}
_last_sides = frozenset()
_platform = None
_fat = None
_big = None
_tiny = None
_rect_region = None

st.angle = 28.0
# Module-level — Oriented page reads it; other pages ignore.
_angle_slider = Slider(
    st["angle"], label="Angle °", show_value=True, min_value=0.0, max_value=90.0
)


def _page(name: str, expect: str, keys: str):
    def deco(fn):
        _PAGES.append((name, expect, keys, fn))
        return fn

    return deco


def _track(obj):
    _owned.append(obj)
    return obj


def _cap(text: str, x: float, y: float, *, size: int = 14) -> None:
    _track(
        Text(
            text=text,
            top_left=(x, y + 15),
            font_size=size,
            color=Color(0.7, 0.75, 0.85, 1),
        )
    )


def _world_cap(text: str, pos, *, size: int = 13) -> None:
    _track(
        Text(
            text=text,
            center=pos,
            font_size=size,
            color=Color(0.78, 0.84, 0.94, 1),
        )
    )


def _draw_outline(region, color, *, width=2.5):
    r = Rect(box=region)
    r.fill = None
    r.line = Color(color) if not isinstance(color, Color) else color
    r.line_width = width
    r.clickable = False
    return _track(r)


def _sync_outline(rect, region):
    if rect is None or region is None:
        return
    rect.center = region.center
    rect.width = region.width
    rect.height = region.height
    rect.angle = region.angle


def _clear():
    global _mover, _ghost, _region, _outline, _platform, _fat, _big, _tiny
    global _rect_region, _last_sides
    for o in list(_owned):
        try:
            if getattr(o, "is_alive", True):
                o.destroy()
        except Exception:
            pass
    _owned.clear()
    _balls.clear()
    _flash_edges.clear()
    _mover = _ghost = _region = _outline = None
    _platform = _fat = _big = _tiny = _rect_region = None
    _last_sides = frozenset()
    canvas.reset_view()


def _flash_side_marks(region, sides):
    """Brief gold ticks on the region edges that were hit (local frame)."""
    for mark in list(_flash_edges.values()):
        try:
            if getattr(mark, "is_alive", True):
                mark.destroy()
        except Exception:
            pass
    _flash_edges.clear()
    if not sides or region is None:
        return
    cx, cy = float(region.center.x), float(region.center.y)
    hw, hh = float(region.width) * 0.5, float(region.height) * 0.5
    ang = float(region.angle)
    rad = math.radians(ang)
    cos_a, sin_a = math.cos(rad), math.sin(rad)

    def local_to_world(lx, ly):
        return (cx + lx * cos_a - ly * sin_a, cy + lx * sin_a + ly * cos_a)

    specs = {
        "left": (-hw, 0.0),
        "right": (hw, 0.0),
        "top": (0.0, hh),
        "bottom": (0.0, -hh),
    }
    for side in sides:
        if side not in specs:
            continue
        wx, wy = local_to_world(*specs[side])
        mark = _track(Circle(center=(wx, wy), radius=10, color="gold"))
        mark.glow = Glow(color="gold", radius=18, sigma=8)
        mark.after(0.35, mark.destroy)
        _flash_edges[side] = mark


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@_page(
    "Clamp",
    "Arrows move the ship. confine(PLAY) clamps the center — same as the Galaga pattern.",
    "A/S page  ·  arrows move  ·  SPACE recenter",
)
def _p_clamp():
    global _mover, _region, _outline
    play = canvas.game_view.inset(60)
    _region = play
    _outline = _draw_outline(play, Color(0.35, 0.85, 1.0, 0.95), width=3)
    _mover = _track(Circle(center=(CONTENT_CX, 120), radius=22, color="skyblue"))
    _mover.glow = Glow(color="skyblue", radius=14, sigma=7)
    _cap("by=\"center\"  action=\"clamp\" (defaults)  ·  cyan = PLAY = game_view.inset(60)", CONTENT_X, H - 148)
    _world_cap("ship", (CONTENT_CX, 70), size=12)
    hud.status = "hold arrows — center cannot leave the cyan box"


@_page(
    "By",
    "Same fat Rect on a platform. Q/W cycles by= center | box | overlap. Ghost = own .box.",
    "A/S page  ·  arrows  ·  Q/W by=  ·  SPACE reset",
)
def _p_by():
    global _mover, _ghost, _region, _outline, _platform, _fat, _by_mode
    _by_mode = "center"
    platform = Box(center=(CONTENT_CX, 380), width=720, height=160)
    _region = platform
    _platform = _draw_outline(platform, Color(0.45, 0.95, 0.55, 0.95), width=3)
    _track(Rect(box=platform, color=Color(0.12, 0.28, 0.18, 0.35), corner_radius=8)).clickable = False
    _fat = _track(
        Rect(
            center=(CONTENT_CX, 380),
            width=120,
            height=70,
            color=Color(0.95, 0.55, 0.25, 0.9),
            corner_radius=10,
        )
    )
    _mover = _fat
    _ghost = _draw_outline(_fat.box, Color(1.0, 0.9, 0.3, 0.85), width=2)
    _cap(
        "green = platform  ·  gold ghost = mover.box  ·  "
        "by=box keeps ghost inside  ·  by=overlap allows hang-out until fully gone",
        CONTENT_X,
        H - 148,
    )
    hud.status = f"by={_by_mode!r}"


@_page(
    "Bounce",
    "action=\"bounce\" flips .vel on the local edge. Needs self.vel. DVD logo energy.",
    "A/S page  ·  SPACE reseed velocities  ·  1/2/3 speed presets",
)
def _p_bounce():
    global _region, _outline
    arena = Box(center=(CONTENT_CX, CONTENT_CY), width=900, height=520)
    _region = arena
    _outline = _draw_outline(arena, Color(0.85, 0.55, 1.0, 0.95), width=3)
    _track(Rect(box=arena, color=Color(0.18, 0.10, 0.22, 0.4), corner_radius=6)).clickable = False
    colors = ("tomato", "gold", "cyan", "lime")
    speeds = ((220, 160), (-180, 200), (260, -140), (-200, -180))
    starts = ((CONTENT_CX - 120, CONTENT_CY + 40), (CONTENT_CX + 80, CONTENT_CY - 60),
              (CONTENT_CX - 40, CONTENT_CY + 100), (CONTENT_CX + 160, CONTENT_CY))
    for color, vel, pos in zip(colors, speeds, starts):
        b = _track(Circle(center=pos, radius=18, color=color))
        b.vel = Vec2(*vel)
        _balls.append(b)
    _cap("each ball: move_by(vel*dt) then confine(arena, action=\"bounce\")", CONTENT_X, H - 148)
    hud.status = "bounce — watch vel flip at edges"


@_page(
    "Wrap",
    "action=\"wrap\" teleports to the opposite edge and keeps the overshoot (no pop).",
    "A/S page  ·  arrows thrust  ·  SPACE stop",
)
def _p_wrap():
    global _mover, _region, _outline
    arena = Box(center=(CONTENT_CX, CONTENT_CY), width=860, height=480)
    _region = arena
    _outline = _draw_outline(arena, Color(0.4, 0.9, 1.0, 0.95), width=3)
    _track(Rect(box=arena, color=Color(0.08, 0.16, 0.22, 0.45), corner_radius=6)).clickable = False
    _mover = _track(Circle(center=(CONTENT_CX, CONTENT_CY), radius=20, color="orange"))
    _mover.vel = Vec2(280, 120)
    _mover.glow = Glow(color="orange", radius=16, sigma=8)
    _cap("wrap carries overshoot — exit right +15 → enter left +15", CONTENT_X, H - 148)
    hud.status = "arrows add thrust  ·  wrap at cyan edge"


@_page(
    "Oriented",
    "Region at an angle. Sides are local (left = region's local left). Bounce + Angle slider.",
    "A/S page  ·  Angle slider  ·  SPACE reseed",
)
def _p_oriented():
    global _mover, _region, _outline, _platform
    st.angle = 28.0
    arena = Box(center=(CONTENT_CX, CONTENT_CY), width=640, height=360, angle=28)
    _region = arena
    _outline = _draw_outline(arena, Color(0.95, 0.82, 0.4, 0.98), width=3)
    _platform = _track(
        Rect(box=arena, color=Color(0.22, 0.18, 0.08, 0.4), corner_radius=4)
    )
    _platform.clickable = False
    _mover = _track(Circle(center=(CONTENT_CX, CONTENT_CY), radius=16, color="tomato"))
    _mover.vel = Vec2(240, 90)
    _cap(
        "gold outline rotates with Angle ° slider  ·  returned sides stay in the region's local frame",
        CONTENT_X,
        H - 148,
    )
    hud.status = "bounce inside a tilted box"


@_page(
    "Edge",
    "Left: too-big by=\"box\" pins to center (remainder). Right: confine against a Rect Graphic.",
    "A/S page  ·  arrows move both  ·  SPACE reset",
)
def _p_edge():
    global _big, _tiny, _region, _rect_region, _outline, _mover
    # Left: small zone, huge circle
    zone = Box(center=(380, CONTENT_CY), width=160, height=200)
    _region = zone
    _draw_outline(zone, Color(0.5, 0.9, 0.6, 0.95), width=3)
    _track(Rect(box=zone, color=Color(0.1, 0.25, 0.14, 0.4))).clickable = False
    _big = _track(Circle(center=(280, CONTENT_CY + 80), radius=90, color=Color(0.9, 0.4, 0.5, 0.75)))
    _world_cap("by=\"box\" too big → pin", (380, CONTENT_CY - 140), size=13)

    # Right: Rect as region (not Box)
    wall = _track(
        Rect(
            center=(1000, CONTENT_CY),
            width=420,
            height=300,
            color=Color(0.15, 0.2, 0.35, 0.5),
            corner_radius=12,
        )
    )
    wall.line = Color(0.55, 0.7, 1.0, 0.95)
    wall.line_width = 3
    wall.clickable = False
    _rect_region = wall
    _tiny = _track(Circle(center=(1000, CONTENT_CY), radius=18, color="cyan"))
    _world_cap("region = Rect Graphic", (1000, CONTENT_CY - 180), size=13)
    _mover = _tiny
    _cap(
        "left: diameter > zone width — confine(..., by=\"box\") pins without raising  ·  "
        "right: same API, region is a Rect",
        CONTENT_X,
        H - 148,
    )
    hud.status = "arrows move both actors"


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


def _rebuild():
    _clear()
    name, expect, keys, fn = _PAGES[_page_i]
    hud.title = f"confine — {name}  ({_page_i + 1}/{len(_PAGES)})"
    hud.expect = expect
    hud.keys = keys
    fn()


def setup(_canvas):
    _rebuild()


def _arrow_delta(dt: float, speed: float = 320.0):
    dx = dy = 0.0
    if keyp("LEFT"):
        dx -= speed * dt
    if keyp("RIGHT"):
        dx += speed * dt
    if keyp("UP"):
        dy += speed * dt
    if keyp("DOWN"):
        dy -= speed * dt
    return dx, dy


def _fmt_sides(sides) -> str:
    if not sides:
        return "—"
    return "{" + ", ".join(sorted(sides)) + "}"


def update(dt):
    global _page_i, _by_mode, _last_sides, _region, _outline

    if keyp.once("A"):
        _page_i = (_page_i - 1) % len(_PAGES)
        _rebuild()
        return
    if keyp.once("S"):
        _page_i = (_page_i + 1) % len(_PAGES)
        _rebuild()
        return

    name = _PAGES[_page_i][0]

    if name == "Clamp":
        if _mover is None:
            return
        if keyp.once("SPACE"):
            _mover.center = (CONTENT_CX, 120)
            hud.status = "recentered"
        dx, dy = _arrow_delta(dt)
        _mover.move_by(dx, dy)
        sides = _mover.confine(_region)
        if sides:
            _flash_side_marks(_region, sides)
            _last_sides = sides
        hud.aux = (
            f"center=({float(_mover.center.x):.0f}, {float(_mover.center.y):.0f})  "
            f"sides={_fmt_sides(_last_sides)}"
        )

    elif name == "By":
        if _fat is None or _region is None:
            return
        if keyp.once("Q"):
            i = _BY_CYCLE.index(_by_mode)
            _by_mode = _BY_CYCLE[(i - 1) % len(_BY_CYCLE)]
            hud.status = f"by={_by_mode!r}"
        if keyp.once("W"):
            i = _BY_CYCLE.index(_by_mode)
            _by_mode = _BY_CYCLE[(i + 1) % len(_BY_CYCLE)]
            hud.status = f"by={_by_mode!r}"
        if keyp.once("SPACE"):
            _fat.center = (CONTENT_CX, 380)
        dx, dy = _arrow_delta(dt, speed=280.0)
        _fat.move_by(dx, dy)
        sides = _fat.confine(_region, by=_by_mode)
        if sides:
            _flash_side_marks(_region, sides)
            _last_sides = sides
        if _ghost is not None:
            _sync_outline(_ghost, _fat.box)
        hud.aux = (
            f"by={_by_mode!r}  "
            f"center=({float(_fat.center.x):.0f}, {float(_fat.center.y):.0f})  "
            f"box={float(_fat.box.width):.0f}×{float(_fat.box.height):.0f}  "
            f"sides={_fmt_sides(_last_sides)}"
        )

    elif name == "Bounce":
        if keyp.once("SPACE") or keyp.once("1"):
            for b, vel in zip(_balls, ((220, 160), (-180, 200), (260, -140), (-200, -180))):
                b.vel = Vec2(*vel)
            hud.status = "velocities reseeded"
        if keyp.once("2"):
            for b in _balls:
                b.vel = Vec2(float(b.vel.x) * 0.5, float(b.vel.y) * 0.5)
            hud.status = "half speed"
        if keyp.once("3"):
            for b in _balls:
                b.vel = Vec2(float(b.vel.x) * 1.5, float(b.vel.y) * 1.5)
            hud.status = "1.5× speed"
        hit_any = frozenset()
        for b in _balls:
            if not getattr(b, "is_alive", True):
                continue
            b.move_by(float(b.vel.x) * dt, float(b.vel.y) * dt)
            sides = b.confine(_region, action="bounce")
            if sides:
                hit_any = hit_any | sides
        if hit_any:
            _flash_side_marks(_region, hit_any)
            _last_sides = hit_any
        speeds = "  ".join(
            f"{float(math.hypot(float(b.vel.x), float(b.vel.y))):.0f}"
            for b in _balls if getattr(b, "is_alive", True)
        )
        hud.aux = f"speeds={speeds}  last_sides={_fmt_sides(_last_sides)}"

    elif name == "Wrap":
        if _mover is None or _region is None:
            return
        if keyp.once("SPACE"):
            _mover.vel = Vec2(0, 0)
            hud.status = "stopped"
        thrust = 420.0
        if keyp("LEFT"):
            _mover.vel.x -= thrust * dt
        if keyp("RIGHT"):
            _mover.vel.x += thrust * dt
        if keyp("UP"):
            _mover.vel.y += thrust * dt
        if keyp("DOWN"):
            _mover.vel.y -= thrust * dt
        _mover.move_by(float(_mover.vel.x) * dt, float(_mover.vel.y) * dt)
        sides = _mover.confine(_region, action="wrap")
        if sides:
            _flash_side_marks(_region, sides)
            _last_sides = sides
            hud.status = f"wrapped {_fmt_sides(sides)}"
        hud.aux = (
            f"vel=({float(_mover.vel.x):.0f}, {float(_mover.vel.y):.0f})  "
            f"pos=({float(_mover.center.x):.0f}, {float(_mover.center.y):.0f})  "
            f"sides={_fmt_sides(_last_sides)}"
        )

    elif name == "Oriented":
        if _mover is None:
            return
        # Live-rebuild region from Angle slider
        ang = float(st.angle)
        _region = Box(center=(CONTENT_CX, CONTENT_CY), width=640, height=360, angle=ang)
        if _outline is not None and getattr(_outline, "is_alive", False):
            _sync_outline(_outline, _region)
        if _platform is not None and getattr(_platform, "is_alive", False):
            _sync_outline(_platform, _region)
        if keyp.once("SPACE"):
            _mover.center = (CONTENT_CX, CONTENT_CY)
            _mover.vel = Vec2(240, 90)
            hud.status = "reseeded"
        _mover.move_by(float(_mover.vel.x) * dt, float(_mover.vel.y) * dt)
        sides = _mover.confine(_region, action="bounce")
        if sides:
            _flash_side_marks(_region, sides)
            _last_sides = sides
        hud.aux = (
            f"angle={ang:.0f}°  "
            f"vel=({float(_mover.vel.x):.0f}, {float(_mover.vel.y):.0f})  "
            f"sides={_fmt_sides(_last_sides)}  (local to region)"
        )

    elif name == "Edge":
        dx, dy = _arrow_delta(dt, speed=260.0)
        if keyp.once("SPACE"):
            if _big is not None:
                _big.center = (280, CONTENT_CY + 80)
            if _tiny is not None:
                _tiny.center = (1000, CONTENT_CY)
            hud.status = "reset"
        sides_big = frozenset()
        sides_tiny = frozenset()
        if _big is not None and _region is not None:
            _big.move_by(dx, dy)
            sides_big = _big.confine(_region, by="box")
            if sides_big:
                _flash_side_marks(_region, sides_big)
        if _tiny is not None and _rect_region is not None:
            _tiny.move_by(dx, dy)
            sides_tiny = _tiny.confine(_rect_region)
            if sides_tiny:
                _last_sides = sides_tiny
        hud.aux = (
            f"big by=box → {_fmt_sides(sides_big)}  "
            f"center=({float(_big.center.x):.0f}, {float(_big.center.y):.0f})  ·  "
            f"tiny vs Rect → {_fmt_sides(sides_tiny)}"
        )


run()
