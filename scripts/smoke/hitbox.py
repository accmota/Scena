"""Auto hitbox lab — visual benchmark for the examples/media hitbox set.

Loads both atlases, standalone PNGs, and shows auto-hitbox picks with overlays.
Prints an aggregate coverage report on startup (stdout).

Controls
--------
  A / S          previous / next page
  0              auto policy (utility: quality − λ × runtime cost)
  1 / 2 / 3 / 4  lab force_kind: circle / ellipse / hull / inscribed rects
  5 / 6          lab force_kind: greedy circles / two ellipses
  Q              cycle author hitbox_shape=  (auto / rect / ellipse / circle / hull)
  F              cycle hitbox_source=    (construct / all / each)
  V              cycle hitbox_anchor=  (center / bottom / top / left / right)
  C              toggle collider outlines
  R              reprint aggregate report
  Slider         hitbox_scale (0.5–1.5)

Magenta dot = hitbox_anchor.

Usage
-----
    python scripts/smoke/hitbox.py
"""
from __future__ import annotations

import math
import os
from collections import Counter
from typing import List, Optional, Tuple

from scena import *
from scena.atlas import (
    _AUTO_QUALITY_BAR,
    auto_collider_for_frame,
    boxes_to_local,
    circle_to_local,
    ellipse_to_local,
    hull_to_local,
    reset_atlas_caches,
)
from scena.sprite import _HITBOX_ANCHORS, _HITBOX_CHOICES, _anchor_on_aabb

# Assets: tracked files in examples/media (scripts/smoke/_media.py).
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _media

_ASSET_DIR = str(_media.MEDIA)


def _asset_path(name: str) -> str:
    return _media.path(name)

_PAGE_SIZE = 24
_COLS = 6
_CELL_W = 180
_CELL_H = 130

_SINGLES = _media.HITBOX_SINGLES

# (label, sheet, frame_name)
Entry = Tuple[str, Sheet, str]


def _collect_entries() -> List[Entry]:
    out: List[Entry] = []
    for atlas_png, atlas_xml in _media.HITBOX_ATLASES:
        png_path = _asset_path(atlas_png)
        xml_path = _asset_path(atlas_xml)
        if not os.path.isfile(png_path) or not os.path.isfile(xml_path):
            continue
        sh = Sheet(png_path, atlas=xml_path)
        for name in sh.names:
            out.append((name, sh, name))
    for name in _SINGLES:
        path = _asset_path(name)
        if os.path.isfile(path):
            sh = Sheet(path)
            out.append((name, sh, sh.names[0]))
    return out


def _apply_collider(sprite: Sprite, col, fr) -> None:
    """Overlay a lab ``force_kind`` fit. Snapshot as base, then fold scale/anchor."""
    sprite._clear_auto_hitbox()
    sprite._hitbox_kind = "auto"
    src_circles = col.circles or ((col.circle,) if col.circle is not None else ())
    if col.kind in ("circle", "circles") and src_circles:
        locals_c = tuple(circle_to_local(*c, fr) for c in src_circles)
        sprite._hitbox_circles = locals_c
        sprite._hitbox_circle = locals_c[0] if len(locals_c) == 1 else None
    elif col.kind in ("ellipse", "ellipses"):
        src_ells = col.ellipses or ((col.ellipse,) if col.ellipse is not None else ())
        if src_ells:
            locals_e = tuple(ellipse_to_local(*e, fr) for e in src_ells)
            sprite._hitbox_ellipses = locals_e
            sprite._hitbox_ellipse = locals_e[0] if len(locals_e) == 1 else None
    elif col.kind == "poly" and col.poly:
        sprite._hitbox_poly = hull_to_local(col.poly, fr)
    elif col.kind == "boxes" and col.boxes:
        sprite._hitbox_boxes = boxes_to_local(col.boxes, fr)
    sprite._commit_hitbox_base()


def _world_hitbox_anchor(sprite: Sprite) -> Tuple[float, float]:
    aabb = sprite._local_prims_aabb()
    cx, cy = sprite.center.x, sprite.center.y
    if aabb is None:
        return (cx, cy)
    ax, ay = _anchor_on_aabb(*aabb, sprite.hitbox.anchor)
    ax, ay = sprite._apply_local_flip(ax, ay)
    w, h = sprite._hitbox_pose_wh()
    ang = math.radians(sprite._draw_angle())
    c = math.cos(ang)
    sn = math.sin(ang)
    lx, ly = ax * w, ay * h
    return (cx + lx * c - ly * sn, cy + lx * sn + ly * c)


def _kind_label(col) -> str:
    if col.kind == "boxes":
        return f"rect{len(col.boxes)}"
    if col.kind == "poly":
        return f"hull{len(col.poly)}"
    if col.kind == "circles":
        return f"circ{len(col.circles)}"
    if col.kind == "ellipses":
        return f"ell{len(col.ellipses)}"
    return col.kind or "none"


def print_report(entries: List[Entry]) -> None:
    reset_atlas_caches()
    kinds: Counter = Counter()
    recalls: List[float] = []
    precisions: List[float] = []
    below_rec = 0
    below_prec = 0
    for _label, sheet, frame_name in entries:
        idx = sheet.frame_index(frame_name)
        fr = sheet._frame_at(idx)
        col = auto_collider_for_frame(sheet.image, fr)
        kinds[_kind_label(col)] += 1
        recalls.append(col.recall)
        precisions.append(col.precision)
        if col.recall < _AUTO_QUALITY_BAR:
            below_rec += 1
        if col.precision < _AUTO_QUALITY_BAR:
            below_prec += 1
    n = len(entries) or 1
    print("=" * 60)
    print("Auto hitbox report — examples/media (_media.HITBOX_*)")
    print("=" * 60)
    print(f"Frames:                {len(entries)}")
    print(f"Avg recall:            {sum(recalls) / n:.3f}")
    print(f"Avg precision:         {sum(precisions) / n:.3f}")
    print(f"Below recall bar:      {below_rec}  (bar={_AUTO_QUALITY_BAR})")
    print(f"Below precision bar:   {below_prec}  (bar={_AUTO_QUALITY_BAR})")
    print("Pick distribution:")
    for k, v in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {k:12s} {v}")
    print("=" * 60)


init(width=1200, height=800, title="Auto Hitbox Lab")
import sys as _sys
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _hud import SmokeHud
hud = SmokeHud(
    title="Auto hitbox",
    expect="Overlay hugs opaque pixels. Magenta = hitbox_anchor. Q = author kinds; 0-6 = lab force.",
    keys="A/S page  ·  0-6 force  ·  Q kind  ·  F from  ·  V anchor  ·  C outlines  ·  R report",
    status="",
)
SkyGradient("night")

st.entries = _collect_entries()
st.page = 0
st.force_kind: Optional[str] = None
st.author_kind = "auto"
st.from_mode = "construct"
st.hitbox_anchor = "center"
st.hitbox_scale = 1.0
st.lab_sprites: List[Sprite] = []
st.lab_labels: List[Text] = []
st.lab_anchors: List[Circle] = []
st.show_col = True

_FROM_CYCLE = ("construct", "all", "each")
_AUTHOR_CYCLE = _HITBOX_CHOICES

if st.entries:
    print_report(st.entries)
else:
    print("WARNING: no sprites found in", _ASSET_DIR)

_empty = Text(
    text="",
    top_left=(400, 401), font_size=18,
)
# Scale under HUD band, clear of bottom FPS
_scale_slider = Slider(
    st.hitbox_scale, label="hitbox_scale", min_value=0.5, max_value=1.5,
    top_left=(20, 698), width=220, show_value=True, 
)


def _clear_page() -> None:
    for s in list(st.lab_sprites):
        if s.is_alive:
            s.destroy()
    for lb in list(st.lab_labels):
        if lb.is_alive:
            lb.destroy()
    for m in list(st.lab_anchors):
        if m.is_alive:
            m.destroy()
    st.lab_sprites.clear()
    st.lab_labels.clear()
    st.lab_anchors.clear()


def _rebuild_page() -> None:
    _clear_page()
    if not st.entries:
        hud.status = "page 0/0  no assets — expected the _media.HITBOX_* files in examples/media/"
        _empty.text = f"No sprites in\n{_ASSET_DIR}"
        collision.show_colliders(False)
        return
    _empty.text = ""
    start = st.page * _PAGE_SIZE
    chunk = st.entries[start:start + _PAGE_SIZE]
    hud.status = _status_line(len(chunk))

    author = str(st.author_kind.value)
    fk = st.force_kind.value
    from_mode = str(st.from_mode.value)
    anchor = str(st.hitbox_anchor.value)
    scale = float(st.hitbox_scale)

    for i, (label, sheet, frame_name) in enumerate(chunk):
        row, col = divmod(i, _COLS)
        x = 90 + col * _CELL_W
        y = 620 - row * _CELL_H
        from_spec = frame_name if from_mode == "construct" else from_mode
        s = Sprite(
            sheet, frame=frame_name, height=72, center=(x, y),
            group="lab", hitbox_shape=author, hitbox_source=from_spec,
            hitbox_anchor=anchor, hitbox_scale=scale,
        )
        s.collidable = True
        idx = sheet.frame_index(frame_name)
        fr = sheet._frame_at(idx)
        if fk:
            col_obj = auto_collider_for_frame(sheet.image, fr, force_kind=fk)
            _apply_collider(s, col_obj, fr)
            tag = _kind_label(col_obj)
            extra = f" r={col_obj.recall:.2f} p={col_obj.precision:.2f}"
        else:
            tag = author
            extra = ""
        st.lab_sprites.append(s)
        short = label if len(label) <= 14 else label[:11] + "..."
        st.lab_labels.append(Text(
            text=f"{short}\n{tag}{extra}",
            top_left=(x - 70, y - 32), font_size=11,  # 2 lines: bottom at y - 58
        ))
        mark = Circle(center=_world_hitbox_anchor(s), radius=4, group="lab-anchor")
        mark.set_color("magenta")
        mark.collidable = False
        st.lab_anchors.append(mark)

    collision.show_colliders(bool(st.show_col))


def _status_line(chunk_n: Optional[int] = None) -> str:
    total_pages = max(1, (len(st.entries) + _PAGE_SIZE - 1) // _PAGE_SIZE) if st.entries else 1
    start = int(st.page.value) * _PAGE_SIZE
    if chunk_n is None:
        chunk_n = min(_PAGE_SIZE, max(0, len(st.entries) - start)) if st.entries else 0
    fk = st.force_kind.value
    mode = f"force={fk}" if fk else f"hitbox={st.author_kind.value}"
    return (
        f"page {int(st.page.value) + 1}/{total_pages}  {mode}  "
        f"from={st.from_mode.value}  anchor={st.hitbox_anchor.value}  "
        f"scale={float(st.hitbox_scale):.2f}  "
        f"showing {chunk_n} / {len(st.entries) if st.entries else 0}"
    )


def _place_anchors() -> None:
    for s, m in zip(st.lab_sprites, st.lab_anchors):
        if s.is_alive and m.is_alive:
            m.center = _world_hitbox_anchor(s)


_rebuild_page()
_last_scale = float(st.hitbox_scale)


def update(dt):
    global _last_scale
    scale = float(st.hitbox_scale)
    if abs(scale - _last_scale) > 1e-4:
        _last_scale = scale
        for s in st.lab_sprites:
            if s.is_alive:
                s.hitbox.scale = scale
        _place_anchors()
        collision.show_colliders(bool(st.show_col))
        hud.status = _status_line()


def _cycle(current, options):
    seq = tuple(options)
    try:
        i = seq.index(str(current))
    except ValueError:
        i = -1
    return seq[(i + 1) % len(seq)]


def on_key_down(key):
    if key == "A":
        st.page = max(0, int(st.page.value) - 1)
        _rebuild_page()
    elif key == "S":
        max_page = max(0, (len(st.entries) - 1) // _PAGE_SIZE) if st.entries else 0
        st.page = min(max_page, int(st.page.value) + 1)
        _rebuild_page()
    elif key == "0":
        st.force_kind = None
        st.author_kind = "auto"
        _rebuild_page()
    elif key == "1":
        st.force_kind = "circle"
        _rebuild_page()
    elif key == "2":
        st.force_kind = "ellipse"
        _rebuild_page()
    elif key == "3":
        st.force_kind = "poly"
        _rebuild_page()
    elif key == "4":
        st.force_kind = "boxes"
        _rebuild_page()
    elif key == "5":
        st.force_kind = "circles"
        _rebuild_page()
    elif key == "6":
        st.force_kind = "ellipses"
        _rebuild_page()
    elif key == "Q":
        st.force_kind = None
        st.author_kind = _cycle(st.author_kind.value, _AUTHOR_CYCLE)
        _rebuild_page()
    elif key == "F":
        st.from_mode = _cycle(st.from_mode.value, _FROM_CYCLE)
        _rebuild_page()
    elif key == "V":
        st.hitbox_anchor = _cycle(st.hitbox_anchor.value, _HITBOX_ANCHORS)
        _rebuild_page()
    elif key == "C":
        st.show_col = not bool(st.show_col)
        collision.show_colliders(bool(st.show_col))
    elif key == "R":
        print_report(st.entries)


run()
