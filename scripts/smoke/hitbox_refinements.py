"""Hitbox refinements — clip, scoped "all", locked kind, numeric anchor, hurtbox.

Real art from ``examples/media`` (no generated stand-ins).

  1  ``hitbox_source="clip"`` — ninja Attack / Dead / Glide, and the pixel_adv
     strips Start / End / Checkpoint. The rect is that clip's union:
     it changes when the clip changes and holds while the clip plays.
  2  ``"all"`` on ``shooter/sheet`` — only some frames are registered.
     Left: four player ships. Center: a mixed clip (ship + button + meteor
     + beam + enemy), so the box swallows those cells. Right: no clips,
     so ``"all"`` is just the meteor on screen.
  3  ``hitbox_shape="auto"`` — Checkpoint and ninja Dead use ``"each"`` (kind locks,
     the fit can breathe). The pixel_adv strips use ``"clip"`` (kind holds
     through the clip; Q/W picks again).
  4  Numeric ``hitbox_anchor`` — two sliders, applied live to Start (Moving) and
     plane/Fly1.png. Scale is under 1 so the box moves about the pin.
     The range passes ±1 (no clamp).
  5  Hitbox part — Start (Moving) walker: gold body rect resolves on the floor,
     ``hero.add_hitbox(group="hurtbox")`` is the cyan per-frame silhouette,
     plane/Fly1.png is the sting.

Collider outlines stay on (green = detect, gold = resolve, cyan = hitbox part).

Controls
--------
  A / S          previous / next page
  Q / W          previous / next clip (pages 1 and 3)
  LEFT / RIGHT   move the walker (page 5)
  SPACE          pause the plane
  sliders        anchor x / y (page 4)

Usage
-----
    python scripts/smoke/hitbox_refinements.py
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

from scena import *
from scena.sprite import _anchor_on_aabb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SAFE_BOTTOM, SmokeHud

W, H = 1480, 960
_MEDIA = Path(__file__).resolve().parents[2] / "examples" / "media"
_INK = Color(0.78, 0.84, 0.94, 1)
_FRAME_NO = re.compile(r"(\d+)\.png$", re.I)

_NINJA_CLIPS = ("Attack", "Dead", "Glide")
_FIGHT_CLIPS = ("run", "run_attack", "attack")
_SHIP_FRAMES = (
    "playerShip1_blue.png",
    "playerShip1_green.png",
    "playerShip1_orange.png",
    "playerShip1_red.png",
)
# Ship first so the union is in ship space — the button/meteor then fatten it.
_MIXED_FRAMES = (
    "playerShip1_blue.png",
    "buttonBlue.png",
    "meteorBrown_big2.png",
    "beamLong1.png",
    "enemyBlack1.png",
)

init(width=W, height=H, window_scale=0.78, title="Smoke — hitbox refinements")
collision.floor = True   # gravity: bodies stand on floors (ramps, lifts, seams)
canvas.background = (0.07, 0.08, 0.11)
collision.show_colliders(True)

_PAGE = 0
_paused = False
_bullet_t = 0.0
_clip_i = 0
_kind_clip_i = 0

hud = SmokeHud(
    title="Hitbox refinements",
    expect="",
    keys="A/S page  ·  Q/W clip  ·  sliders anchor x/y  ·  LEFT/RIGHT walker  ·  SPACE pause plane",
    status="",
    show_aux=True,
)

_EXPECT = (
    'rect + hitbox_source="clip". Q/W changes the clip. The box follows the clip and holds while it plays.',
    'shooter/sheet. "all" is registered clips only — four ships, a mixed clip, or this meteor when nothing is registered.',
    'auto. "each" locks kind while the fit breathes. "clip" holds kind, then Q/W can pick a new one.',
    "Sliders write hitbox_anchor=(x, y). Scale is under 1, so the box moves about the pin. Past ±1 still counts.",
    "Gold rect resolves on the floor. Cyan hitbox part is the live silhouette. The plane is the sting.",
)
_STATUS0 = ("clip", "all", "kind", "anchor", "hurtbox")


def _png(name: str) -> str:
    path = _MEDIA / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path.resolve())


def _ninja_frames(prefix: str) -> list[str]:
    folder = _MEDIA / "ninja"
    found = [
        p for p in folder.iterdir()
        if p.suffix.lower() == ".png" and p.name.startswith(prefix)
    ]

    def _key(path: Path) -> int:
        match = _FRAME_NO.search(path.name)
        return int(match.group(1)) if match else 0

    found.sort(key=_key)
    if len(found) < 2:
        raise FileNotFoundError(f"need ninja frames {prefix!r} in {folder}")
    return [str(p.resolve()) for p in found]


def _stems(files: list[str]) -> list[str]:
    return [Path(f).stem for f in files]


def _label(text: str, x: float, y: float = 690.0):
    return Text(text=text, top_left=(x - 150, y + 18), font_size=15, color=_INK, stack=False)


def _ninja_sheet() -> Sheet:
    attack = _ninja_frames("Attack")
    dead = _ninja_frames("Dead")
    glide = _ninja_frames("Glide")
    sheet = Sheet(attack + dead + glide)
    sheet.clip("Attack", _stems(attack), fps=10)
    sheet.clip("Dead", _stems(dead), fps=6)
    sheet.clip("Glide", _stems(glide), fps=8)
    return sheet


_RUN = "pixel_adv/Start (Moving) (64x64).png"   # one 17-cell strip


def _fight_sheet() -> Sheet:
    # Cells are 64×64. Start 1088 wide (17), End 64 (1), Checkpoint 640 (10).
    sheet = Sheet(_png(_RUN), cols=17, fps=10, name="run")
    sheet.strip("run_attack", _png("pixel_adv/End (Idle).png"), cols=1, fps=10)
    sheet.strip("attack", _png("pixel_adv/Checkpoint (Flag Idle)(64x64).png"), cols=10, fps=8)
    return sheet


def _space_sheet() -> Sheet:
    return Sheet(_png("shooter/sheet.png"), atlas=_png("shooter/sheet.xml"))


def _kind_name(sprite: Sprite) -> str:
    """Author-facing name. The fitter stores a hull as ``poly``."""
    kind = sprite._hitbox_locked_kind
    if not kind:
        return "—"
    if kind == "poly":
        return "hull"
    return str(kind)


def _anchor_dot(sprite: Sprite, dot: Circle) -> None:
    aabb = sprite._local_prims_aabb()
    cx, cy = float(sprite.center.x), float(sprite.center.y)
    if aabb is None:
        dot.center = (cx, cy)
        return
    ax, ay = _anchor_on_aabb(*aabb, sprite.hitbox.anchor)
    bw, bh = sprite._hitbox_pose_wh()
    dot.center = (cx + ax * bw, cy + ay * bh)


# --- catalogs -----------------------------------------------------------------
_ninja = _ninja_sheet()
_fight = _fight_sheet()
_run_only = Sheet(_png(_RUN), cols=17, fps=12, name="run")
_run_still = Sheet(_png(_RUN), cols=17)

_ships_sheet = _space_sheet()
_ships_sheet.clip("ships", list(_SHIP_FRAMES), fps=3)
_still_sheet = _space_sheet()
_mixed_sheet = _space_sheet()
_mixed_sheet.clip("mixed", list(_MIXED_FRAMES), fps=1)


def _build_clip():
    ninja = Sprite(
        _ninja, height=250, center=(400, 430),
        hitbox_shape="rect", hitbox_source="clip",
    )
    ninja.play("Attack")
    ninja.collidable = True
    fight = Sprite(
        _fight, height=230, center=(1060, 430),
        hitbox_shape="rect", hitbox_source="clip",
    )
    fight.play("run")
    fight.collidable = True
    return [
        ninja, fight,
        _label('ninja   hitbox_source="clip"', 400),
        _label('Start / End / Checkpoint', 1060),
    ]


def _build_all():
    ships = Sprite(
        _ships_sheet, height=150, center=(280, 450),
        hitbox_shape="rect", hitbox_source="all",
    )
    ships.play("ships")
    ships.collidable = True
    mixed = Sprite(
        _mixed_sheet, frame="playerShip1_blue.png", height=150, center=(740, 450),
        hitbox_shape="rect", hitbox_source="all",
    )
    mixed.collidable = True
    meteor = Sprite(
        _still_sheet, frame="meteorBrown_big1.png", height=150, center=(1180, 450),
        hitbox_shape="rect", hitbox_source="all",
    )
    meteor.collidable = True
    return [
        ships, mixed, meteor,
        _label('"all" · four ships only', 280),
        _label('"all" · ship + button + meteor', 740),
        _label('"all" · no clips, this meteor', 1180),
    ]


def _build_kind():
    slash = Sprite(
        _fight, height=220, center=(280, 440),
        hitbox_shape="auto", hitbox_source="each",
    )
    slash.play("attack")
    slash.collidable = True
    fall = Sprite(
        _ninja, height=240, center=(740, 430),
        hitbox_shape="auto", hitbox_source="each",
    )
    fall.play("Dead")
    fall.collidable = True
    clip = Sprite(
        _fight, height=220, center=(1180, 440),
        hitbox_shape="auto", hitbox_source="clip",
    )
    clip.play("run")
    clip.collidable = True
    return [
        slash, fall, clip,
        _label('Checkpoint · auto + "each"', 280),
        _label('ninja Dead · auto + "each"', 740),
        _label('Start / Checkpoint · auto + "clip"', 1180),
    ]


def _build_anchor():
    # scale < 1 makes the pin visible: the box moves when the sliders move.
    pair = (-0.5, 0.0)
    scale = (0.55, 0.72)
    runner = Sprite(
        _run_still, frame=0, height=240, center=(480, 470),
        hitbox_shape="rect", hitbox_anchor=pair, hitbox_scale=scale,
    )
    runner.collidable = True
    plane = Sprite(
        _png("plane/Fly1.png"), height=170, center=(1040, 470),
        hitbox_shape="rect", hitbox_anchor=pair, hitbox_scale=scale,
    )
    plane.collidable = True
    dots = []
    for sprite in (runner, plane):
        dot = Circle(center=sprite.center, radius=6, color=Color(1, 0.2, 0.85, 1))
        _anchor_dot(sprite, dot)
        dots.append(dot)
    return [
        runner, plane, *dots,
        _label("Start (Moving)", 480),
        _label("plane/Fly1.png", 1040),
    ]


def _build_hurt():
    hero = Sprite(
        _run_only, height=150, center=(480, 420),
        hitbox_shape="rect", hitbox_source="all",
        hitbox_anchor="bottom", hitbox_scale=(0.55, 1.0),
        group="hero",
    )
    hero.mass = 1.0
    hero.collidable = True
    # Detection-only part: follows each frame (and tilt); never resolves.
    hero.add_hitbox(group="hurtbox")
    floor = Rect(
        center=(740, 160), width=1200, height=28,
        color=Color(0.25, 0.28, 0.34, 1), group="floor",
    )
    floor.mass = STATIC
    floor.collidable = True
    sting = Sprite(
        _png("plane/Fly1.png"), height=56, center=(1100, 340), group="sting",
    )
    sting.collidable = True
    resolve("hero", "floor", bounce=0.0)

    @collide("hurtbox", "sting")
    def _on_hit(a, b, info):
        hud.status = "silhouette hit — the rect still owns the floor"

    return [
        hero, floor, sting,
        _label("gold rect = body    cyan = hitbox part (silhouette)", 740),
    ]


_PAGES = [
    _build_clip(),
    _build_all(),
    _build_kind(),
    _build_anchor(),
    _build_hurt(),
]
_clip_ninja = _PAGES[0][0]
_clip_fight = _PAGES[0][1]
_scoped = _PAGES[1][0]
_mixed = _PAGES[1][1]
_meteor = _PAGES[1][2]
_each_slash = _PAGES[2][0]
_each_fall = _PAGES[2][1]
_kind_clip = _PAGES[2][2]
_anchor_sprites = [a for a in _PAGES[3] if isinstance(a, Sprite)]
_anchor_dots = [a for a in _PAGES[3] if isinstance(a, Circle)]
_walker = _PAGES[4][0]
_plane = _PAGES[4][3]

st.ax = -0.5
st.ay = 0.0


def _apply_anchor(*_args) -> None:
    pair = (float(st.ax), float(st.ay))
    for sprite in _anchor_sprites:
        sprite.hitbox.anchor = pair


@on_change(st["ax"])
@on_change(st["ay"])
def _on_anchor(*_args):
    _apply_anchor()


_slider_x = Slider(
    st["ax"], label="anchor x", min_value=-1.5, max_value=1.5,
    top_left=(48, SAFE_BOTTOM + 106), width=360, show_value=True,
)
_slider_y = Slider(
    st["ay"], label="anchor y", min_value=-1.5, max_value=1.5,
    top_left=(48, SAFE_BOTTOM + 60), width=360, show_value=True,
)


def _show(page: int) -> None:
    global _PAGE
    _PAGE = page % len(_PAGES)
    for i, actors in enumerate(_PAGES):
        on = i == _PAGE
        for actor in actors:
            actor.active = on
    on_anchor = _PAGE == 3
    _slider_x.visible = on_anchor
    _slider_y.visible = on_anchor
    hud.expect = _EXPECT[_PAGE]
    hud.status = _STATUS0[_PAGE]
    hud.aux = ""


def _cycle(index: int, step: int, names: tuple[str, ...]) -> int:
    return (index + step) % len(names)


def update(dt):
    global _bullet_t
    if _PAGE == 0:
        hud.status = f"{_NINJA_CLIPS[_clip_i]}    ·    {_FIGHT_CLIPS[_clip_i]}"
        hud.aux = (
            f"ninja frame {_clip_ninja.frame}    "
            f"fighter frame {_clip_fight.frame}"
        )
    elif _PAGE == 1:
        hud.status = "registered clips, not the whole atlas"
        hud.aux = (
            f"atlas {_ships_sheet.nframes} cells    "
            f"ships {len(_scoped._hitbox_from_indices())}    "
            f"mixed {len(_mixed._hitbox_from_indices())}    "
            f"meteor {len(_meteor._hitbox_from_indices())}"
        )
    elif _PAGE == 2:
        hud.status = f"clip {_FIGHT_CLIPS[_kind_clip_i]}"
        hud.aux = (
            f"each Checkpoint  frame {_each_slash.frame}  kind {_kind_name(_each_slash)}"
            f"     each Dead  frame {_each_fall.frame}  kind {_kind_name(_each_fall)}"
            f"     clip {_FIGHT_CLIPS[_kind_clip_i]}  frame {_kind_clip.frame}"
            f"  kind {_kind_name(_kind_clip)}"
        )
    elif _PAGE == 3:
        for sprite, dot in zip(_anchor_sprites, _anchor_dots):
            _anchor_dot(sprite, dot)
        hud.status = "numeric anchor"
        hud.aux = f"hitbox_anchor = ({float(st.ax):.2f}, {float(st.ay):.2f})    scale (0.55, 0.72)"
    elif _PAGE == 4 and not _paused:
        _bullet_t += dt
        phase = _bullet_t * 1.1
        _plane.center = (740 + 480 * math.sin(phase), 340)
        _plane.flip_x = math.cos(phase) < 0
        x = float(_walker.center.x)
        if keyp("LEFT"):
            x -= 260 * dt
            _walker.flip_x = False
        if keyp("RIGHT"):
            x += 260 * dt
            _walker.flip_x = True
        x = min(1200.0, max(160.0, x))
        _walker.center = (x, float(_walker.center.y))
        _walker.vel = Vec2(0, -520)
        _walker.move_by(0, float(_walker.vel.y) * dt)
        hud.aux = "arrows move the runner    SPACE pauses the plane"
    elif _PAGE == 4:
        hud.aux = "plane paused"


def on_key_down(key):
    global _paused, _clip_i, _kind_clip_i
    if key == "A":
        _show(_PAGE - 1)
    elif key == "S":
        _show(_PAGE + 1)
    elif key == "Q" and _PAGE == 0:
        _clip_i = _cycle(_clip_i, -1, _NINJA_CLIPS)
        _clip_ninja.play(_NINJA_CLIPS[_clip_i])
        _clip_fight.play(_FIGHT_CLIPS[_clip_i])
    elif key == "W" and _PAGE == 0:
        _clip_i = _cycle(_clip_i, 1, _NINJA_CLIPS)
        _clip_ninja.play(_NINJA_CLIPS[_clip_i])
        _clip_fight.play(_FIGHT_CLIPS[_clip_i])
    elif key == "Q" and _PAGE == 2:
        _kind_clip_i = _cycle(_kind_clip_i, -1, _FIGHT_CLIPS)
        _kind_clip.play(_FIGHT_CLIPS[_kind_clip_i])
    elif key == "W" and _PAGE == 2:
        _kind_clip_i = _cycle(_kind_clip_i, 1, _FIGHT_CLIPS)
        _kind_clip.play(_FIGHT_CLIPS[_kind_clip_i])
    elif key == "SPACE":
        _paused = not _paused


_show(0)
run()
