"""Animated sprite hitbox lab — ninja (one PNG per frame) and grid strips (pixel_adv).

Tunes the four author knobs while a clip plays: ``hitbox`` (primitive),
``hitbox_from`` (which art), ``hitbox_anchor`` / ``hitbox_scale`` (shaping,
per-axis). Collider outlines stay on. Magenta dot = anchor. Faint white =
design box (often larger than the silhouette collider).

Controls
--------
  A / S          previous / next spritesheet
  Q / W          previous / next clip on this sheet (combined sheets)
  SPACE          pause / resume the playhead
  C              toggle collider outlines
  widgets        kind / from / anchor / scale x,y / flip / spin
  Platformer     hitbox_shape=rect, from=all, anchor=bottom, scale=(0.55, 1)
  Reset          constructor defaults

Usage
-----
    python scripts/smoke/hitbox_frames.py
"""
from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from scena import *
from scena.sprite import _HITBOX_ANCHORS, _HITBOX_CHOICES, _anchor_on_aabb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
_FPS = 8.0
_HERO_HEIGHT = 180.0
_HERO_POS = (820.0, 380.0)

_HERE = Path(__file__).resolve().parent
_NINJA_DIR = _HERE.parents[1] / "examples" / "media" / "ninja"
_STRIP_DIR = _HERE.parents[1] / "examples" / "media" / "pixel_adv"
_CLIP_FILE = re.compile(r"^(?P<clip>.+?)_{1,2}(?P<idx>\d+)\.png$", re.I)

# Grid strips (one row each): clip name -> (file, author-facing cols).
_STRIPS = {
    "flag": ("Checkpoint (Flag Idle)(64x64).png", 10),
    "start": ("Start (Moving) (64x64).png", 17),
}
_NINJA_CLIP_ORDER = (
    "Idle", "Run", "Jump", "Attack", "Throw",
    "Jump_Attack", "Jump_Throw", "Glide", "Climb", "Slide", "Dead",
)


@dataclass
class Catalog:
    label: str
    clips: Tuple[str, ...]
    play: str
    factory: Callable[[], Sheet]
    _sheet: Optional[Sheet] = field(default=None, repr=False)

    @property
    def sheet(self) -> Sheet:
        if self._sheet is None:
            self._sheet = self.factory()
        return self._sheet


def _ninja_groups() -> List[Tuple[str, List[str]]]:
    groups: dict[str, List[str]] = {}
    if not _NINJA_DIR.is_dir():
        return []
    for path in sorted(_NINJA_DIR.iterdir(), key=lambda p: p.name.lower()):
        if path.suffix.lower() != ".png":
            continue
        match = _CLIP_FILE.match(path.name)
        if match is None:
            continue
        groups.setdefault(match.group("clip"), []).append(str(path.resolve()))
    ordered: List[Tuple[str, List[str]]] = []
    seen = set()
    for name in _NINJA_CLIP_ORDER:
        files = groups.get(name)
        if files:
            ordered.append((name, files))
            seen.add(name)
    for name, files in groups.items():
        if name not in seen:
            ordered.append((name, files))
    return ordered


def _grid_sheet(path: Path, cols_hint: int) -> Sheet:
    """Load a 1-row strip. Fall back to 128px cells when ``cols_hint`` does not tile."""
    source = str(path.resolve())
    try:
        return Sheet(source, cols=int(cols_hint))
    except ValueError:
        return Sheet(source, cell=(128, 128))


def _add_grid_clip(sheet: Sheet, path: Path, cols_hint: int, name: str) -> None:
    source = str(path.resolve())
    try:
        sheet.strip(name, source, cols=int(cols_hint), fps=_FPS)
    except ValueError:
        sheet.strip(name, source, cell=(128, 128), fps=_FPS)


def _ninja_factory(name: str, files: List[str]) -> Callable[[], Sheet]:
    def make() -> Sheet:
        sh = Sheet(files)
        sh.clip(name, [Path(f).stem for f in files], fps=_FPS)
        return sh
    return make


def _strip_one_factory(name: str, path: Path) -> Callable[[], Sheet]:
    def make() -> Sheet:
        sh = _grid_sheet(path, _STRIPS[name][1])
        sh.clip(name, fps=_FPS)
        return sh
    return make


def _strip_all_factory(items: List[Tuple[str, Path]]) -> Callable[[], Sheet]:
    def make() -> Sheet:
        first_name, first_path = items[0]
        sh = _grid_sheet(first_path, _STRIPS[first_name][1])
        sh.clip(first_name, fps=_FPS)
        for name, path in items[1:]:
            _add_grid_clip(sh, path, _STRIPS[name][1], name)
        return sh
    return make


def _collect_catalog() -> List[Catalog]:
    out: List[Catalog] = []
    for name, files in _ninja_groups():
        out.append(Catalog(f"ninja {name}", (name,), name, _ninja_factory(name, files)))

    strip_files: List[Tuple[str, Path]] = [
        (name, _STRIP_DIR / file)
        for name, (file, _cols) in _STRIPS.items()
        if (_STRIP_DIR / file).is_file()
    ]

    if strip_files:
        clips = tuple(name for name, _p in strip_files)
        out.append(Catalog(
            "strips (all clips)", clips, clips[0],
            _strip_all_factory(strip_files),
        ))
        for name, path in strip_files:
            out.append(Catalog(
                f"strip {name}", (name,), name,
                _strip_one_factory(name, path),
            ))
    return out


def _from_options(cat: Catalog) -> List[str]:
    opts = ["all", "each"]
    for name in cat.clips:
        if name not in opts:
            opts.append(name)
    # Single-clip sheets: also offer cell names (ninja stems / grid indices).
    if len(cat.clips) == 1:
        names = list(cat.sheet.names)
        if 0 < len(names) <= 12:
            for name in names:
                if name not in opts:
                    opts.append(name)
        elif names and names[0] not in opts:
            opts.append(names[0])
    return opts


def _world_hitbox_anchor(sprite: Sprite) -> Tuple[float, float]:
    aabb = sprite._local_prims_aabb()
    cx, cy = sprite.center.x, sprite.center.y
    if aabb is None:
        return (cx, cy)
    ax, ay = _anchor_on_aabb(*aabb, sprite.hitbox.anchor)
    ax, ay = sprite._apply_local_flip(ax, ay)
    box_w, box_h = sprite._hitbox_pose_wh()
    ang = math.radians(sprite._draw_angle())
    c, sn = math.cos(ang), math.sin(ang)
    lx, ly = ax * box_w, ay * box_h
    return (cx + lx * c - ly * sn, cy + lx * sn + ly * c)


def _cycle_index(i: int, n: int, step: int) -> int:
    if n <= 0:
        return 0
    return (i + step) % n


init(width=W, height=H, window_scale=0.78, title="Smoke — hitbox frames")
canvas.background = (0.07, 0.08, 0.11)
SkyGradient("night")
Stars(density=0.25, twinkle=0.08)

hud = SmokeHud(
    title="Hitbox frames",
    expect="Green = collider. White = design box. Magenta = hitbox_anchor. from=each moves with the clip; all/clip stay frozen.",
    keys="A/S sheet  ·  Q/W clip  ·  SPACE pause  ·  C outlines  ·  widgets = kind/from/anchor/scale",
    status="",
    show_aux=True,
)

_CATALOG = _collect_catalog()
st.sheet_i = 0
st.clip_i = 0
st.hitbox = "auto"
st.hitbox_from = "all"
st.hitbox_anchor = "center"
st.scale_x = 1.0
st.scale_y = 1.0
st.show_col = True
st.animate = True
st.flip_x = False
st.flip_y = False
st.spin = False
st.angle = 0.0

ui.gap()
ui.gap()
Text(text="hitbox", font_size=12, color=Color(0.7, 0.76, 0.88, 1))
DropDown(st.hitbox, options=list(_HITBOX_CHOICES))
Text(text="hitbox_from", font_size=12, color=Color(0.7, 0.76, 0.88, 1))
_from_dd = DropDown(st.hitbox_from, options=["all", "each"])
Text(text="hitbox_anchor", font_size=12, color=Color(0.7, 0.76, 0.88, 1))
DropDown(st.hitbox_anchor, options=list(_HITBOX_ANCHORS))
Slider(st.scale_x, label="hitbox_scale x", min_value=0.2, max_value=1.8, show_value=True)
Slider(st.scale_y, label="hitbox_scale y", min_value=0.2, max_value=1.8, show_value=True)
CheckBox(st.show_col, label="show colliders")
CheckBox(st.animate, label="play clip")
CheckBox(st.flip_x, label="flip_x")
CheckBox(st.flip_y, label="flip_y")
CheckBox(st.spin, label="spin")
Slider(st.angle, label="angle °", min_value=0.0, max_value=360.0, show_value=True)


def _platformer_recipe():
    st.hitbox = "rect"
    st.hitbox_from = "all"
    st.hitbox_anchor = "bottom"
    st.scale_x = 0.55
    st.scale_y = 1.0
    st.spin = False
    st.flip_x = False
    st.flip_y = False
    st.angle = 0.0
    hud.status = "platformer recipe: rect + all + bottom + (0.55, 1.0)"


def _reset_defaults():
    st.hitbox = "auto"
    st.hitbox_from = "all"
    st.hitbox_anchor = "center"
    st.scale_x = 1.0
    st.scale_y = 1.0
    st.spin = False
    st.flip_x = False
    st.flip_y = False
    st.angle = 0.0
    hud.status = "reset: auto + all + center + (1, 1)"


Button(label="Platformer recipe", on_click=_platformer_recipe)
Button(label="Reset defaults", on_click=_reset_defaults)

hero: Optional[Sprite] = None
guide: Optional[Rect] = None
anchor_mark: Optional[Circle] = None
_caption = Text(
    text="",
    top_left=(_HERO_POS[0] - 140, _HERO_POS[1] - 113),
    font_size=14,
    color=Color(0.78, 0.84, 0.94, 1),
    stack=False,
)
_syncing = False


def _current_catalog() -> Optional[Catalog]:
    if not _CATALOG:
        return None
    return _CATALOG[int(st.sheet_i) % len(_CATALOG)]


def _refresh_from_dropdown(cat: Catalog) -> None:
    global _syncing
    opts = _from_options(cat)
    _from_dd.options = opts
    if str(st.hitbox_from) not in opts:
        _syncing = True
        try:
            st.hitbox_from = "all" if "all" in opts else opts[0]
        finally:
            _syncing = False


def _destroy_lab() -> None:
    global hero, guide, anchor_mark
    if hero is not None and hero.is_alive:
        hero.destroy()
    if guide is not None and guide.is_alive:
        guide.destroy()
    if anchor_mark is not None and anchor_mark.is_alive:
        anchor_mark.destroy()
    hero = None
    guide = None
    anchor_mark = None


def _spawn() -> None:
    global hero, guide, anchor_mark
    cat = _current_catalog()
    if cat is None:
        hud.status = f"no art — expected {_NINJA_DIR} and {_STRIP_DIR}"
        _caption.text = "No ninja / strip sheets found"
        collision.show_colliders(False)
        return

    clips = cat.clips
    clip_i = int(st.clip_i) % len(clips) if clips else 0
    st.clip_i = clip_i
    play = clips[clip_i] if clips else cat.play
    pose = (
        (float(hero.center.x), float(hero.center.y))
        if hero is not None and hero.is_alive else None
    )
    _destroy_lab()
    _refresh_from_dropdown(cat)

    cx, cy = pose if pose is not None else _HERO_POS
    hero = Sprite(
        cat.sheet,
        height=_HERO_HEIGHT,
        center=(cx, cy),
        group="lab",
        hitbox_shape=str(st.hitbox),
        hitbox_source=str(st.hitbox_from),
        hitbox_anchor=str(st.hitbox_anchor),
        hitbox_scale=(float(st.scale_x), float(st.scale_y)),
    )
    hero.collidable = True
    hero.draggable = True
    hero.flip_x = bool(st.flip_x)
    hero.flip_y = bool(st.flip_y)
    hero.angle = float(st.angle)
    hero.play(play)
    hero.time_scale = 1.0 if bool(st.animate) else 0.0

    guide = Rect(
        center=hero.center, width=hero.width, height=hero.height,
    )
    guide.fill = None
    guide.line = Color(1.0, 1.0, 1.0, 0.28)
    guide.line_width = 1
    guide.collidable = False

    ax, ay = _world_hitbox_anchor(hero)
    anchor_mark = Circle(center=(ax, ay), radius=5, group="lab-anchor")
    anchor_mark.set_color("magenta")
    anchor_mark.collidable = False

    collision.show_colliders(bool(st.show_col))
    _caption.text = f"{cat.label}  ·  {play}"
    _status()


def _apply_hitbox() -> None:
    if _syncing or hero is None or not hero.is_alive:
        return
    hero.hitbox.shape = str(st.hitbox)
    try:
        hero.hitbox.source = str(st.hitbox_from)
    except (TypeError, ValueError):
        cat = _current_catalog()
        if cat is not None:
            _refresh_from_dropdown(cat)
            hero.hitbox.source = str(st.hitbox_from)
    hero.hitbox.anchor = str(st.hitbox_anchor)
    hero.hitbox.scale = (float(st.scale_x), float(st.scale_y))
    _status()


def _sync_rotation_from_hero() -> None:
    global _syncing
    if hero is None or not hero.is_alive:
        return
    _syncing = True
    try:
        st.angle = float(hero.angle) % 360.0
    finally:
        _syncing = False


def _status() -> None:
    cat = _current_catalog()
    if cat is None or hero is None or not hero.is_alive:
        return
    n = len(_CATALOG)
    sheet_i = int(st.sheet_i) % max(n, 1)
    clip = cat.clips[int(st.clip_i) % len(cat.clips)] if cat.clips else "?"
    sx, sy = hero.hitbox.scale
    hud.status = (
        f"{sheet_i + 1}/{n}  {cat.label}  clip={clip}  "
        f"frame={int(hero.frame)}/{cat.sheet.nframes}  "
        f"hitbox={hero.hitbox.shape}  from={hero.hitbox.source}  "
        f"anchor={hero.hitbox.anchor}  scale=({sx:.2f}, {sy:.2f})"
    )
    hud.aux = (
        f"{'playing' if bool(st.animate) else 'paused'}  "
        f"flip_x={hero.flip_x}  flip_y={hero.flip_y}  "
        f"rot={hero.angle:.0f}°  "
        f"outlines={'ON' if st.show_col else 'OFF'}"
    )


def _step_sheet(step: int) -> None:
    if not _CATALOG:
        return
    st.sheet_i = _cycle_index(int(st.sheet_i), len(_CATALOG), step)
    st.clip_i = 0
    _spawn()


def _step_clip(step: int) -> None:
    cat = _current_catalog()
    if cat is None or hero is None or not hero.is_alive:
        return
    st.clip_i = _cycle_index(int(st.clip_i), len(cat.clips), step)
    play = cat.clips[int(st.clip_i)]
    hero.play(play)
    _caption.text = f"{cat.label}  ·  {play}"
    _status()


@on_change(st.hitbox)
@on_change(st.hitbox_from)
@on_change(st.hitbox_anchor)
@on_change(st.scale_x)
@on_change(st.scale_y)
def _on_hitbox(_value=None):
    _apply_hitbox()


@on_change(st.animate)
def _on_animate(play):
    if hero is not None and hero.is_alive:
        hero.time_scale = 1.0 if bool(play) else 0.0
    _status()


@on_change(st.show_col)
def _on_outlines(show):
    collision.show_colliders(bool(show))
    _status()


@on_change(st.flip_x)
def _on_flip_x(v):
    if hero is not None and hero.is_alive:
        hero.flip_x = bool(v)
        _sync_rotation_from_hero()
    _status()


@on_change(st.flip_y)
def _on_flip_y(v):
    if hero is not None and hero.is_alive:
        hero.flip_y = bool(v)
        _sync_rotation_from_hero()
    _status()


@on_change(st.angle)
def _on_rotation(deg):
    if _syncing or bool(st.spin):
        return
    if hero is not None and hero.is_alive:
        hero.angle = float(deg)
    _status()


@on_change(st.spin)
def _on_spin(spin):
    if not bool(spin):
        _sync_rotation_from_hero()
    _status()


if _CATALOG:
    _spawn()
else:
    Text(
        text=f"No sprites in\n{_NINJA_DIR}\n{_STRIP_DIR}",
        top_left=(500, 464), font_size=18, stack=False,  # 3 lines: bottom at 400
    )


def update(dt):
    if hero is None or not hero.is_alive:
        return
    if bool(st.spin):
        hero.rotate_by(50.0 * dt)
        _sync_rotation_from_hero()
    if guide is not None and guide.is_alive:
        guide.center = (hero.center.x, hero.center.y)
        guide.width = float(hero.width)
        guide.height = float(hero.height)
        guide.angle = hero._draw_angle()
    if anchor_mark is not None and anchor_mark.is_alive:
        anchor_mark.center = _world_hitbox_anchor(hero)
    _status()


def on_key_down(key):
    if key == "A":
        _step_sheet(-1)
    elif key == "S":
        _step_sheet(1)
    elif key == "Q":
        _step_clip(-1)
    elif key == "W":
        _step_clip(1)
    elif key == "SPACE":
        st.animate = not bool(st.animate)
    elif key == "C":
        st.show_col = not bool(st.show_col)


run()
