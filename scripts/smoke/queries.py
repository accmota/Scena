"""queries.py — smoke: collision.query_* and raycast, with the result on screen.

Gold fill = reported hit. Blue = caster (the origin); it must stay blue.
Tomato = ignore=; it must stay tomato. Dim = tested and not hit.
Magenta = a caster or an ignored body was reported (a failure).

Pages (A / S)
-------------
  1  query_point(mouse) — only a hitbox that contains the cursor.
  2  query_circle — the blue disk is the probe and the caster.
  3  query_shape — drag the gold rectangle. Blue bodies are another group.
  4  query_sector — wedge follows the guard's angle. SPACE pauses.
  5  raycast — first hit only, then three fixed shots.

Usage
-----
    python scripts/smoke/queries.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SAFE_BOTTOM, SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.78, title="Smoke — collision queries")
canvas.background = (0.07, 0.08, 0.11)

HIT = Color("gold")
DIM = Color(0.38, 0.42, 0.50, 1)
CASTER = Color("dodger blue")
IGNORE = Color("tomato")
OUT = Color("deep sky blue")
FAIL = Color("magenta")
INK = Color(0.78, 0.84, 0.94, 1)

hud = SmokeHud(
    title="Collision queries",
    expect="",
    keys="A/S page  ·  mouse aims point and circle  ·  drag the rectangle  ·  SPACE pause sweep  ·  C outlines",
    status="",
    show_aux=True,
)

_PAGE = 0
_paused = False
_outlines = False
_pointer_seen = False
_phase = 0.0
collision.show_colliders(False)

_EXPECT = (
    "query_point(mouse). Gold = the cursor is inside that hitbox. Overlap both circles and both light. No radius.",
    "query_circle(disk, radius=100). The blue disk follows the mouse. Gold = overlap, including just a rim. Tomato is ignore= and stays tomato. The disk does not count itself.",
    "query_shape(rectangle). The dark gold frame is the probe. Drag it. A body inside turns gold. It does not count itself. Sky-blue bodies are not in the group.",
    "query_sector(guard, radius=230, spread=70). Gold = inside the wedge, including a partial overlap. Blue guard is the caster. Tomato is ignore=.",
    "raycast. Top: only the first body on the ray turns gold; the line stops there. Bottom: three shots, labeled.",
)


def _solid(shape, color):
    shape.color = color
    shape.line = color
    return shape


def _body(shape):
    shape.collidable = True
    return shape


def _caption(text, x, y):
    return Text(text=text, top_left=(x, y + 18), font_size=15, color=INK)


def _label(text, body, dy):
    return Text(
        text=text, top_left=(float(body.center.x) - 18, float(body.center.y) + dy + 17),
        font_size=14, color=INK,
    )


def _paint(bodies, hits, *, caster=(), ignored=(), outsiders=()):
    found = {id(b) for b in hits}
    skip = {id(b) for b in caster}
    denied = {id(b) for b in ignored}
    other = {id(b) for b in outsiders}
    for body in bodies:
        bid = id(body)
        wrongly = bid in found and (bid in skip or bid in denied)
        if wrongly:
            _solid(body, FAIL)
        elif bid in skip:
            _solid(body, CASTER)
        elif bid in denied:
            _solid(body, IGNORE)
        elif bid in other:
            _solid(body, OUT)
        elif bid in found:
            _solid(body, HIT)
        else:
            _solid(body, DIM)


def _names(hits):
    if not hits:
        return "none"
    return ", ".join(getattr(b, "id", "?") or "?" for b in hits)


def _make_line(color, width):
    return Line(p1=(0, 0), p2=(10, 0), color=color, line_width=width)


def _show_ray(line, dot, origin, end, hit):
    line.p1 = origin
    if hit is None:
        line.p2 = end
        dot.visible = False
    else:
        line.p2 = hit[2]
        dot.move_to(hit[2])
        dot.visible = True


# --- page 1: query_point -----------------------------------------------------
_pt_a = _body(Circle(center=(520, 460), radius=52, group="q_point"))
_pt_b = _body(Circle(center=(590, 430), radius=40, group="q_point"))
_pt_c = _body(Rect(center=(860, 480), width=110, height=64, group="q_point"))
_pt_d = _body(Ellipse(center=(780, 300), width=130, height=64, group="q_point"))
_pt_cross_h = Line(p1=(0, 0), p2=(10, 0), color="white", line_width=2)
_pt_cross_v = Line(p1=(0, 0), p2=(0, 10), color="white", line_width=2)
_pt_note = _caption("cursor is the point — no radius. Park it on a shape.", 480, 220)
_point_actors = [
    _pt_a, _pt_b, _pt_c, _pt_d, _pt_cross_h, _pt_cross_v, _pt_note,
    _label("circle", _pt_a, 64), _label("overlap", _pt_b, 52),
    _label("box", _pt_c, 48), _label("ellipse", _pt_d, 48),
]
_point_bodies = [_pt_a, _pt_b, _pt_c, _pt_d]

# --- page 2: query_circle ----------------------------------------------------
_disk = _body(Circle(center=(700, 420), radius=100, group="q_circle"))
_disk.line_width = 3
_ci_in = _body(Circle(center=(700, 470), radius=22, group="q_circle"))
_ci_edge = _body(Circle(center=(812, 420), radius=22, group="q_circle"))
_ci_out = _body(Circle(center=(1040, 420), radius=28, group="q_circle"))
_ci_skip = _body(Circle(center=(640, 360), radius=26, group="q_circle"))
_ci_note = _caption("disk starts on A and the rim of B, then follows the mouse", 430, 220)
_circle_actors = [
    _disk, _ci_in, _ci_edge, _ci_out, _ci_skip, _ci_note,
    _label("A", _ci_in, 36), _label("B", _ci_edge, 36),
    _label("C", _ci_out, 44), _label("ignore", _ci_skip, 42),
]
_circle_bodies = [_disk, _ci_in, _ci_edge, _ci_out, _ci_skip]

# --- page 3: query_shape -----------------------------------------------------
_PROBE_FILL = Color(0.10, 0.11, 0.14, 0.45)
_probe = Rect(
    center=(700, 420), width=150, height=90,
    color=_PROBE_FILL, group="q_shape",
)
_probe.line = HIT
_probe.line_width = 3
_probe.collidable = True
_probe.draggable = True
_sh_a = _body(Circle(center=(700, 420), radius=22, group="q_shape"))
_sh_b = _body(Rect(center=(1020, 420), width=80, height=80, group="q_shape"))
_sh_c = _body(Ellipse(center=(700, 250), width=90, height=50, group="q_shape"))
_sh_out_a = _body(Circle(center=(760, 420), radius=28, group="q_other"))
_sh_out_b = _body(Rect(center=(640, 420), width=50, height=70, group="q_other"))
_sh_note = _caption(
    "gold rect already covers one in-group body and two sky-blue bodies. Drag it.",
    360, 220,
)
_shape_actors = [
    _probe, _sh_a, _sh_b, _sh_c, _sh_out_a, _sh_out_b, _sh_note,
    _label("in group", _sh_a, 40), _label("in group", _sh_b, 56),
    _label("in group", _sh_c, 40), _label("other group", _sh_out_a, 44),
    _label("other group", _sh_out_b, 52),
]
_shape_bodies = [_sh_a, _sh_b, _sh_c, _sh_out_a, _sh_out_b]

# --- page 4: query_sector ----------------------------------------------------
_GUARD = (500, 430)
_SPREAD = 70
_REACH = 230
_guard = _body(
    Rect(center=_GUARD, width=56, height=20, color=CASTER, group="q_sector"),
)
_guard.line = CASTER
_sec_in = _body(Circle(center=(640, 430), radius=24, group="q_sector"))
_sec_part = _body(Circle(center=(730, 430), radius=26, group="q_sector"))
_sec_far = _body(Circle(center=(820, 430), radius=20, group="q_sector"))
_sec_side = _body(Circle(center=(600, 590), radius=22, group="q_sector"))
_sec_skip = _body(Circle(center=(630, 480), radius=22, group="q_sector"))
_sec_fill = Color("gold")
_sec_fill.alpha = 0.28
_sec_wedge = Circle(
    center=_GUARD,
    radius=_REACH,
    spread=_SPREAD,
    use_center=True,
    color=_sec_fill,
    line_width=1.5,
)
_sec_wedge.line = Color("gold")
_sec_wedge["angle"] @= lambda: _guard.angle
_sec_note = _caption("wedge = angle ± 35°    reach 230    SPACE pauses the sweep", 360, 200)
_sector_actors = [
    _sec_wedge, _guard, _sec_in, _sec_part, _sec_far, _sec_side, _sec_skip, _sec_note,
    _label("0°, in reach", _sec_in, 40), _label("0°, on the rim", _sec_part, 42),
    _label("past the rim", _sec_far, 36), _label("off the start aim", _sec_side, -48),
    _label("ignore", _sec_skip, 38),
]
_sector_bodies = [_guard, _sec_in, _sec_part, _sec_far, _sec_side, _sec_skip]

# --- page 5: raycast ---------------------------------------------------------
_TURRET = (520, 600)
_RAY = 500
_turret = _body(
    Rect(center=_TURRET, width=48, height=18, color=CASTER, group="q_ray"),
)
_turret.line = CASTER
_ray_near = _body(Circle(center=(700, 600), radius=28, group="q_ray"))
_ray_mid = _body(Circle(center=(860, 600), radius=28, group="q_ray"))
_ray_far = _body(Circle(center=(1020, 600), radius=28, group="q_ray"))
_ray_off = _body(Circle(center=(860, 730), radius=24, group="q_ray"))
_ray_ghost = _make_line(Color(1, 0.84, 0.3, 0.28), 2)
_ray_line = _make_line(HIT, 3)
_ray_dot = Circle(center=(0, 0), radius=7, color="white")
_ray_dot.visible = False
_ray_note = _caption("only the first body on the ray — the bright line stops, the faint line is the full length", 360, 520)

def _shot(y, group, label):
    hero = _body(Rect(center=(180, y), width=40, height=28, color=CASTER, group=group))
    hero.line = CASTER
    enemy = _body(Circle(center=(620, y), radius=24, group=group))
    wall = _body(Rect(center=(400, y), width=26, height=70, group=group))
    note = _caption(label, 760, y - 8)
    return hero, enemy, wall, note

_los_clear = _shot(210, "q_clear", "ignore=enemy  →  no hit")
_los_dest = _shot(290, "q_dest", "no ignore  →  enemy is the hit")
_los_wall = _shot(370, "q_wall", "wall in front  →  wall is the hit, enemy ignored")
# The clear and dest rows have no wall.
_los_clear[2].active = False
_los_dest[2].active = False

_los_lines = [_make_line(HIT, 3) for _ in range(3)]
_los_dots = []
for _ in range(3):
    dot = Circle(center=(0, 0), radius=7, color="white")
    dot.visible = False
    _los_dots.append(dot)

_ray_actors = [
    _turret, _ray_near, _ray_mid, _ray_far, _ray_off,
    _ray_ghost, _ray_line, _ray_dot, _ray_note,
    _label("on the start aim", _ray_near, 44), _label("on the start aim", _ray_mid, 44),
    _label("on the start aim", _ray_far, 44), _label("off the aim", _ray_off, 40),
    *_los_clear, *_los_dest, *_los_wall,
    *_los_lines, *_los_dots,
]
_ray_bodies = [_turret, _ray_near, _ray_mid, _ray_far, _ray_off]

_PAGES = [
    _point_actors,
    _circle_actors,
    _shape_actors,
    _sector_actors,
    _ray_actors,
]


def _show(page: int) -> None:
    global _PAGE
    _PAGE = page % len(_PAGES)
    for i, actors in enumerate(_PAGES):
        on = i == _PAGE
        for actor in actors:
            actor.active = on
    hud.title = f"Collision queries    {_PAGE + 1}/{len(_PAGES)}"
    hud.expect = _EXPECT[_PAGE]
    hud.aux = ""


def update(dt):
    global _phase, _pointer_seen
    if _PAGE == 0:
        x, y = float(mouse.x), float(mouse.y)
        _pt_cross_h.p1 = (x - 14, y)
        _pt_cross_h.p2 = (x + 14, y)
        _pt_cross_v.p1 = (x, y - 14)
        _pt_cross_v.p2 = (x, y + 14)
        hits = collision.query_point(mouse, group="q_point")
        _paint(_point_bodies, hits)
        hud.status = f"query_point  →  {_names(hits)}"
    elif _PAGE == 1:
        if _pointer_seen or mouse.x or mouse.y:
            _pointer_seen = True
            _disk.move_to(mouse)
        hits = collision.query_circle(
            _disk, radius=100, group="q_circle", ignore=_ci_skip,
        )
        _paint(_circle_bodies, hits, caster=(_disk,), ignored=(_ci_skip,))
        hud.status = f"query_circle  →  {_names(hits)}"
    elif _PAGE == 2:
        hits = collision.query_shape(_probe, group="q_shape")
        _paint(_shape_bodies, hits, outsiders=(_sh_out_a, _sh_out_b))
        if _probe in hits:
            _solid(_probe, FAIL)
        else:
            _probe.color = _PROBE_FILL
            _probe.line = HIT
        hud.status = f"query_shape  →  {_names(hits)}"
    elif _PAGE == 3:
        if not _paused:
            _phase += dt
            _guard.angle = _phase * 40.0
        hits = collision.query_sector(
            _guard, radius=_REACH, spread=_SPREAD,
            group="q_sector", ignore=_sec_skip,
        )
        _paint(_sector_bodies, hits, caster=(_guard,), ignored=(_sec_skip,))
        hud.status = (
            f"query_sector  angle={_guard.angle:.0f}  →  {_names(hits)}"
        )
        hud.aux = "SPACE pauses the sweep"
    elif _PAGE == 4:
        if not _paused:
            _phase += dt
        _turret.angle = 22.0 * math.sin(_phase)
        ang = math.radians(_turret.angle)
        end = (
            _TURRET[0] + _RAY * math.cos(ang),
            _TURRET[1] + _RAY * math.sin(ang),
        )
        shot = collision.raycast(_turret, length=_RAY, group="q_ray")
        _ray_ghost.p1 = _turret.center
        _ray_ghost.p2 = end
        _show_ray(_ray_line, _ray_dot, _turret.center, end, shot)
        _paint(_ray_bodies, [shot[0]] if shot else [], caster=(_turret,))

        rows = (
            (_los_clear, "q_clear", True),
            (_los_dest, "q_dest", False),
            (_los_wall, "q_wall", True),
        )
        bits = [f"first={shot[0]}" if shot else "first=none"]
        for spec, line, dot in zip(rows, _los_lines, _los_dots):
            (hero, enemy, wall, _note), group, skip_enemy = spec
            members = [hero, enemy, wall] if group == "q_wall" else [hero, enemy]
            hit = collision.raycast(
                hero, p2=enemy, group=group,
                ignore=enemy if skip_enemy else None,
            )
            _show_ray(line, dot, hero.center, enemy.center, hit)
            _paint(
                members, [hit[0]] if hit else [],
                caster=(hero,), ignored=(enemy,) if skip_enemy else (),
            )
            bits.append(f"{group}={hit[0] if hit else 'none'}")
        hud.status = "    ".join(bits)
        hud.aux = "SPACE pauses the sweep"


def on_key_down(key):
    global _paused, _outlines
    if key == "A":
        _show(_PAGE - 1)
    elif key == "S":
        _show(_PAGE + 1)
    elif key == "SPACE":
        _paused = not _paused
    elif key == "C":
        _outlines = not _outlines
        collision.show_colliders(_outlines)


# Those two walls are parked. Keep them out of the page so A/S does not
# turn them back on (they would sit on the clear and dest shots).
_ray_actors.remove(_los_clear[2])
_ray_actors.remove(_los_dest[2])

_legend = _caption(
    "gold = hit    blue = caster    tomato = ignore    dim = miss    sky = other group    magenta = reported by mistake",
    24, SAFE_BOTTOM + 10,
)

_show(0)
run()
