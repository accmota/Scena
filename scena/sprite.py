"""Sprite + Sheet: image-body actors (Slice 4–6).

A Sprite is a Graphic, not a Shape and not a Texture-filled Rect. On-demand
``Sprite("potion.png")`` loads through a process-wide cache and an interned
single-frame catalog — repeated paths share one decoded image and one Sheet.
``Sheet`` is the catalog for shared clips (``clip``, optional ``yoyo=True``
ping-pong), packed atlases, grid strips, and extra strip files (``strip``).
``clone()`` makes another actor that looks like this one (constructor +
``setup()``, then a look snapshot). ``fps=`` on a Sheet registers a named
clip (default ``\"default\"``; override with ``name=``); pass ``yoyo=True``
for ping-pong. ``Sprite(sheet)`` autoplays when that catalog has exactly
one clip (omit ``frame=``). Missing files, missing atlas catalogs, and
unknown atlas frame names warn once and stay legal (magenta/black checker
placeholder). Unexpected constructor keywords raise ``TypeError``.

``flip_x`` / ``flip_y`` mirror about the pivot before rotation and reflect
``.angle`` on toggle (``180 − θ`` / ``−θ``). ``art_angle`` is the bitmap
nose in degrees (0 = +x, 90 = +y). Draw uses ``angle − art'`` where ``art'``
is ``art_angle`` after flip reflection. ``.angle`` is world heading
(frente pintada). Construct seeds ``angle`` to ``rest_heading``. Subclasses
may declare omit-able look defaults via
``class Bolt(Sprite, source=\"laser.png\", height=28)`` (not class attributes
named ``frame`` / ``height`` — those would shadow descriptors).

``Svg`` is a Sprite whose pixels come from SVG: the first positional is markup
if it contains ``<``, otherwise a filename (same resolve as Sprite: absolute,
then the running script's folder, then ``media/`` next to it, then cwd). ``.svg``
always stores markup (file contents after load). Writing ``.svg`` uses the
same rule. Still only (no clips).

Slice 5: packed atlas (JSON / Kenney XML), multi-file clips, per-frame pivot,
``hitbox="ellipse"`` / ``hitbox="auto"``.

Slice 6: overlay looks on ``.visual`` (Glow / Shadow / Halo / Tail / Beat);
ElectricField / ElectricBolt hug the live silhouette; Shield uses a frozen
silhouette-union ellipse (costume envelope × ``shield_scale``);
body-replacing looks raise ``TypeError``.
"""
from __future__ import annotations

import builtins
import math
import os
import re
import sys
import heapq
import itertools
import warnings
import weakref
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union, overload

import numpy as np
import skia

from ._defaults import Unset
from .atlas import (
    AtlasFrame,
    _display_mask,
    auto_collider_for_frame,
    auto_collider_for_frames,
    boxes_to_local,
    circle_to_local,
    compose_strip,
    ellipse_as_circle,
    ellipse_to_local,
    hull_to_local,
    is_atlas_filename,
    load_atlas,
    reset_atlas_caches,
)
from .entity import Graphic, _STYLE_PAINT, _USE_LAYER_DEFAULT, _refuse_if_destroyed
from .shapes import (
    Point,
    GeneralPoint,
    get_xy,
    _bare_num,
    _bare_attr,
    _takein_xy_float,
    _translate_point_float,
    _pose_fast_ok,
    _DEFAULT_EXTENT_FRAC,
    _default_pose,
    _ensure_writable,
)
from .style import (
    PaintState,
    LookLike,
    SPRITE_BODY,
    is_sprite_body,
    coerce_visual,
    BlendMode,
    _SKIA_BLEND_MAP,
    gpu_image,
)
from .state import Attribute, Container, ContainerSlot, ScalarSlot, as_payload, _init_composite, batch_update_self, probe_private, bump_pose_rev
from .validate import HINT_EXTENT
from .process import _DUE_EPS, reached
from .closed import ClosedSurface, seal

# Warnings point at the author's line: every frame inside the package is
# skipped (graphics review PA14: Sheet warnings pointed at sprite.py).
_WARN_SKIP = (os.path.dirname(os.path.abspath(__file__)) + os.sep,)


def _sq(v: float) -> float:
    """``v * v``. Not ``v ** 2``: a float power raises OverflowError for a
    huge-but-finite author coordinate; a product saturates to inf."""
    return v * v

# ---------------------------------------------------------------------------
# Image cache / placeholder
# ---------------------------------------------------------------------------

_IMAGE_CACHE: Dict[str, skia.Image] = {}
_MISSING_WARNED: set = set()
_SVG_WARNED: set = set()
_STALE_HITBOX_WARNED: set = set()
_PLACEHOLDER_CACHE: Dict[str, skia.Image] = {}
_SVG_MIN_PX = 128
_SVG_SHEET_KWARGS = frozenset({
    "cols", "rows", "cell", "fps", "name", "yoyo", "atlas",
})
# Catalog knobs live on Sheet. Sprite rejects them with a teaching TypeError.
_SPRITE_CATALOG_KEYS = frozenset({
    "cols", "rows", "cell", "atlas", "fps", "name", "yoyo",
})
_VIEWBOX_RE = re.compile(
    r'viewBox\s*=\s*["\']?\s*'
    r'([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)',
)

_CHECKER_MAGENTA = 0xFFFF00FF
_CHECKER_BLACK = 0xFF101010
_PLACEHOLDER_SIDE = 64
_CHECKER_CELLS = 8

_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear)
# The cached blit plan (Sprite Design, "Blit plan cache"). False: every blit
# computes its transform (oracle, A/B).
_BLIT_PLAN = True
_pose_rev_of_fn = None
_cull_mover_fn = None
_collision_mod = None


def _plan_verify() -> bool:
    """Verify mode (``SCENA_VERIFY_POSE_REV=1``): a cached blit plan is
    recomputed and compared on every use."""
    global _collision_mod
    mod = _collision_mod
    if mod is None:
        from .collision import _pose_rev_of
        mod = _collision_mod = sys.modules[_pose_rev_of.__module__]
    return mod._POSE_REV_VERIFY


def _draw_blit(skia_canvas, cx, cy, ops, image, paint) -> None:
    """One Sprite blit from ``Sprite._blit_geometry``: the steps of
    ``_apply_paint_xform`` at ``(cx, cy)``, then a rotated cell's turn. A
    cached plan and a fresh blit both draw here, so they issue the same
    calls (Sprite Design, "Blit plan cache")."""
    draw_ang, seat, lean, fx, fy, turn, src, dst = ops
    skia_canvas.save()
    skia_canvas.translate(cx, cy)
    if draw_ang:
        skia_canvas.rotate(draw_ang)
    if seat is not None:
        skia_canvas.translate(seat[0], seat[1])
    if lean is not None:
        px, py, tilt = lean
        skia_canvas.translate(px, py)
        skia_canvas.rotate(tilt)
        skia_canvas.translate(-px, -py)
    skia_canvas.scale(fx, -fy)
    if turn is not None:
        skia_canvas.translate(turn[0], turn[1])
        skia_canvas.rotate(-90.0)
    skia_canvas.drawImageRect(image, src, dst, _SAMPLING, paint)
    skia_canvas.restore()


def _plain_geo(geo):
    """``_blit_geometry``'s answer with the rects as tuples (comparable)."""
    if geo is None:
        return None
    cx, cy, (draw_ang, seat, lean, fx, fy, turn, src, dst) = geo
    return (cx, cy, draw_ang, seat, lean, fx, fy, turn, tuple(src), tuple(dst))
_BLIT_PAINT = skia.Paint(AntiAlias=True)
_MAX_GRID_CELLS = 1024
_HITBOX_CHOICES = ("auto", "rect", "ellipse", "circle", "hull")
HitboxSpec = Literal["auto", "rect", "ellipse", "circle", "hull"]
_HITBOX_FROM_SPECIAL = ("all", "each", "clip")

# ``add_hitbox`` art-knob default: "left out", as opposed to an explicit
# ``hitbox_from="each"`` (a px shape refuses the latter). ``hitbox.py`` shares it.
class _AddHitboxUnset:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<default>"


_ADD_HITBOX_UNSET = _AddHitboxUnset()
_HITBOX_ANCHORS = ("center", "bottom", "top", "left", "right")
# y-up local: (0, 0) center, (0, -1) bottom, (0, 1) top, (-1, 0) left, (1, 0) right.
# Not clamped — |component| > 1 extrapolates past the AABB.
_HITBOX_ANCHOR_XY = {
    "center": (0.0, 0.0),
    "bottom": (0.0, -1.0),
    "top": (0.0, 1.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
}
# AutoCollider.kind → force_kind for a locked refit (no second competition).
_AUTO_KIND_FORCE = {
    "circle": "circle",
    "circles": "circles",
    "ellipse": "ellipse",
    "ellipses": "ellipses",
    "poly": "poly",
    "boxes": "boxes",
}
_HITBOX_FROM_EXPECT = (
    'a frame index, a frame name, a clip name, "all", "each", "clip", '
    "or a tuple of clip names"
)
# Author kind → atlas force_kind. ``"auto"`` is the utility picker (None).
_HITBOX_FORCE_KIND = {
    "rect": "bbox",
    "ellipse": "bbox_ellipse",
    "circle": "circle",
    "hull": "poly",
}
_DEFAULT_CLIP_NAME = "default"
# Shield costume on sprites sits outside the silhouette envelope (per-sprite override).
_SPRITE_SHIELD_SCALE = 1.4

# Auto tilt sentinel: lean to one bottom contact and, when the anchor is the
# feet, seat that point on the contact plane along the normal.
# Authors can use either `sprite.tilt = AUTO_GROUND` or `sprite.tilt = "ground"`.
AUTO_GROUND = "ground"


def _sdf_quad_pad(fr, dw: float, dh: float) -> Tuple[float, float]:
    """``(pad_x, pad_y)`` of the SDF band quad around a ``dw`` x ``dh`` cell
    drawn from frame ``fr``, sized as ``atlas.frame_fx_for_frame`` sizes the
    mask (no bake): the SDF border over the mask side, in draw units."""
    from .atlas import _FX_MAX_SIDE, _FX_SDF_PAD
    w = max(1, int(fr.w))
    h = max(1, int(fr.h))
    scale = min(1.0, float(_FX_MAX_SIDE) / float(max(w, h)))
    tw = max(1, int(round(w * scale)))
    th = max(1, int(round(h * scale)))
    if fr.rotated:                          # the mask is turned to the display
        tw, th = th, tw
    return abs(dw) * _FX_SDF_PAD / tw, abs(dh) * _FX_SDF_PAD / th


def _uses_shield_envelope(shape) -> bool:
    """True when the host has a Shield costume envelope (Sprite-only).

    Envelope methods (``_shield_envelope_half`` / ``_shield_envelope_frame``)
    exist only on Sprite. Shape hosts (Circle / Ellipse / …) map ProceduralFill
    UV via ``_center_radius`` — do **not** key only on ``.visual`` being Shield.
    That wrongly routed Shape Shield into the Sprite path; ``to_skia_fill_paint``
    then swallowed ``AttributeError`` and fell back to fixed-res ``tick()``,
    emptying bubble/nebula interiors (2026-09). See Effect System Design §5.5.
    """
    if not callable(getattr(shape, "_shield_envelope_half", None)):
        return False
    vis = getattr(shape, "_visual", None)
    if vis is None:
        return False
    from .entity import scena_kind
    return scena_kind(vis) == "Shield" or getattr(vis, "_VARIANT", None) == "shield_halo"


def _sprite_ellipse_scale(shape) -> float:
    """``shield_scale`` for Shield / plasma orb on Sprite; else 1.0."""
    if not _uses_shield_envelope(shape):
        return 1.0
    sc = getattr(shape, "_shield_scale", None)
    if sc is None:
        return _SPRITE_SHIELD_SCALE
    return float(sc)


# Sentinel: keyword was omitted so class look defaults may fill it.
_OMIT = Unset("<unset>")

_SPRITE_DEFAULT_KEYS = frozenset({
    "source", "frame", "width", "height", "size",
    "hitbox_shape", "hitbox_source", "hitbox_anchor", "hitbox_scale", "shield_scale", "offset",
    "visual", "group", "flip_x", "flip_y", "art_angle",
})
_SPRITE_PLACEMENT_KEYS = frozenset({"center", "layer", "box"})
_SPRITE_CTOR_KEYS = _SPRITE_DEFAULT_KEYS | _SPRITE_PLACEMENT_KEYS


# Catalog knobs on Sprite / Svg point the author at Sheet. Also the
# constructor's ``_call_hints`` (unknown keyword → actor wrapper message).
_SPRITE_CATALOG_HINTS: Dict[str, str] = {
    "cols": 'cols= belongs on Sheet, not Sprite. Write Sheet("hero.png", cols=4, rows=3) then Sprite(sheet)',
    "rows": 'rows= belongs on Sheet, not Sprite. Write Sheet("hero.png", cols=4, rows=3) then Sprite(sheet)',
    "cell": 'cell= belongs on Sheet, not Sprite. Write Sheet("hero.png", cols=4, rows=3) then Sprite(sheet)',
    "atlas": 'atlas= belongs on Sheet, not Sprite. Write Sheet("sheet.png", atlas="sheet.json") then Sprite(sheet)',
    "fps": 'fps= belongs on Sheet (constructor, clip, or strip). Write Sheet("snail.png", cols=8, fps=6) then Sprite(sheet)',
    "name": 'name= names a Sheet clip. Write Sheet("idle.png", cols=4, fps=6, name="idle") then Sprite(sheet)',
    "yoyo": 'yoyo= belongs on Sheet.clip / strip. Write sheet.clip("idle", [0, 1], fps=6, yoyo=True)',
    # Retired spellings of the main hitbox's knobs (every hitbox is a Hitbox).
    "hitbox": 'hitbox= is now hitbox_shape= (Sprite(..., hitbox_shape="rect")); after construction, sprite.hitbox.shape = "rect"',
    "hitbox_from": 'hitbox_from= is now hitbox_source= (Sprite(..., hitbox_source="all")); after construction, sprite.hitbox.source = "all"',
}


def _reject_sprite_catalog_kwargs(extra: Dict[str, Any]) -> None:
    """Catalog knobs on Sprite / Svg: point the author at Sheet."""
    for key in ("cols", "rows", "cell", "atlas", "fps", "name", "yoyo", "hitbox", "hitbox_from"):
        if key in extra:
            raise TypeError(_SPRITE_CATALOG_HINTS[key] + ".")


def _reject_unexpected_sprite_kwargs(
    cls_name: str,
    extra: Dict[str, Any],
    *,
    class_kw: bool = False,
) -> None:
    """Raise ``TypeError`` listing unknown Sprite keywords (instance or class)."""
    from .validate import reject_unexpected_kwargs

    _reject_sprite_catalog_kwargs(extra)
    allowed = _SPRITE_DEFAULT_KEYS if class_kw else _SPRITE_CTOR_KEYS
    reject_unexpected_kwargs(
        cls_name,
        extra,
        valid=allowed,
        where="class definition" if class_kw else "constructor",
    )


def reset_sprite_caches() -> None:
    """Test hook: drop decoded images, missing-file warnings, interned sheets."""
    _IMAGE_CACHE.clear()
    from .style import _unpin_images
    _unpin_images()
    _MISSING_WARNED.clear()
    _SVG_WARNED.clear()
    _STALE_HITBOX_WARNED.clear()
    _PLACEHOLDER_CACHE.clear()
    _TRUE_CASE.clear()
    _PACK_CACHE.clear()
    Sheet._intern.clear()
    reset_atlas_caches()


def _frame_fx_needs(look) -> Tuple[bool, bool]:
    """Return ``(needs_path, needs_sdf)`` for a look class or instance.

    ``needs_sdf`` implies path work as well. Unknown values → ``(False, False)``.
    """
    if look is None:
        return False, False
    src = look  # class or instance — getattr works on both
    need_sdf = bool(getattr(src, "_needs_sprite_sdf", False))
    need_path = bool(
        getattr(src, "_needs_sprite_path", False)
        or getattr(src, "_replaces_sprite_body", False)
        or need_sdf
    )
    return need_path, need_sdf


def _world_time() -> float:
    clk = getattr(builtins, "clock", None)
    if clk is None:
        return 0.0
    try:
        return float(clk.time)
    except Exception:
        return 0.0


def _positive_number(value, *, what: str, exclusive: bool = True) -> float:
    from .validate import magnitude, fixed_magnitude
    if callable(value):
        # Sprite sizes are fixed numbers (no live formula): say so instead of
        # leaking an arithmetic error later (A4).
        raise TypeError(f"{what} expected a number, got a function")
    return fixed_magnitude(value, what, positive=exclusive)


def _clip_period(n: int, yoyo: bool) -> int:
    """Ticks in one loop of a clip. Yoyo is a round trip that does not hold the end twice."""
    if n <= 1:
        return 1
    if yoyo:
        return 2 * (n - 1)
    return n


def _clip_step(idx: int, n: int, yoyo: bool) -> int:
    """Map a tick onto a frame index in ``0..n-1`` (wrapping cycle or yoyo ping-pong)."""
    if n <= 1:
        return 0
    if not yoyo:
        return idx % n
    period = 2 * (n - 1)
    p = idx % period
    if p < n:
        return p
    return period - p


def _script_dir() -> Optional[str]:
    """Directory of the running program (``__main__.__file__``), or None."""
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None) if main is not None else None
    if not path:
        argv0 = sys.argv[0] if sys.argv else ""
        if argv0 and argv0 not in ("-c", "-m", "-", ""):
            path = argv0
    if not path or str(path).startswith("<"):
        return None
    return os.path.dirname(os.path.abspath(path))


def _resolve_image_path(filename: str) -> Optional[str]:
    """Locate ``filename`` for Sprite / Sheet / Texture / Wallpaper / Svg.

    Order (first existing file wins; the string is used as written, never
    walked or stripped to a basename):

    1. Absolute path — that file only (exist or miss).
    2. Next to the running script (``__main__``).
    3. ``media/`` next to that script.
    4. Current working directory.

    REPL / ``python -c`` have no script file: skip to cwd. Missing → ``None``.
    """
    if not filename or not isinstance(filename, str):
        return None
    for ap in _image_candidates(filename):
        if os.path.isfile(ap):
            return _true_case_path(ap, filename)
    return None


_TRUE_CASE: Dict[str, str] = {}
# Strips packed from file lists, keyed by the decoded images (PA-note).
_PACK_CACHE: Dict[tuple, Tuple[skia.Image, Tuple[AtlasFrame, ...]]] = {}


def _true_case_path(ap: str, written: str) -> str:
    """``ap`` spelled as on disk. On a disk that ignores case (macOS, Windows)
    ``"Hero.PNG"`` opened ``hero.png``: it failed on Linux, where patterns
    already matched by case, and one image got two cache entries (graphics
    review PA9). Warns once per spelling; the disk's spelling is the key."""
    hit = _TRUE_CASE.get(ap)
    if hit is not None:
        return hit
    real = ap
    head, parts = ap, []
    while True:
        head, tail = os.path.split(head)
        if not tail:
            break
        parts.append(tail)
    parts.reverse()
    cur = head
    for part in parts:
        try:
            entries = os.listdir(cur)
        except OSError:
            real = ap
            break
        if part not in entries:
            low = part.lower()
            match = [e for e in entries if e.lower() == low]
            if len(match) == 1:
                part = match[0]
        cur = os.path.join(cur, part)
    else:
        real = cur
    if real != ap and written not in _MISSING_WARNED:
        _MISSING_WARNED.add(written)
        warnings.warn(
            f"Image {written!r} was found as {os.path.basename(real)!r} only because this "
            "disk ignores letter case; on Linux it is missing. Write the name as on disk.",
            RuntimeWarning,
            skip_file_prefixes=_WARN_SKIP,
        )
    _TRUE_CASE[ap] = real
    return real


# ``_image_candidates`` answers, keyed by the name, the script folder and the
# working directory's identity (device, inode, change time: a deleted folder's
# inode can come back as a new folder's, which has another change time).
# ``os.getcwd()`` costs ~6 µs on macOS and ran once per Sprite built;
# ``os.stat(".")`` costs ~0.7 µs. Only the list of places is kept: which of
# them holds the file is still asked on every call, so a file that appears or
# goes away is seen as before.
_CANDIDATES: Dict[tuple, Tuple[str, ...]] = {}
_CANDIDATES_MAX = 4096


def _image_candidates(filename: str) -> Tuple[str, ...]:
    """Absolute paths ``_resolve_image_path`` tries, in order, without repeats."""
    if os.path.isabs(filename):
        return (os.path.abspath(filename),)
    script = _script_dir()
    try:
        here = os.stat(".")
    except OSError:
        here = None                       # no working directory: no memo
    if here is not None:
        key = (filename, script, here.st_dev, here.st_ino, here.st_ctime_ns)
        hit = _CANDIDATES.get(key)
        if hit is not None:
            return hit
    candidates: List[str] = []
    if script:
        candidates.append(os.path.join(script, filename))
        candidates.append(os.path.join(script, "media", filename))
    candidates.append(os.path.join(os.getcwd(), filename))
    out: List[str] = []
    for p in candidates:
        ap = os.path.abspath(p)
        if ap not in out:
            out.append(ap)
    found = tuple(out)
    if here is not None:
        if len(_CANDIDATES) >= _CANDIDATES_MAX:
            _CANDIDATES.clear()
        _CANDIDATES[key] = found
    return found


# ---------------------------------------------------------------------------
# File patterns (``Sheet("ninja/Run__*.png")`` / ``strip(name, "…*.png")``)
# ---------------------------------------------------------------------------
# A filename with ``*`` is a list of files written short: legal exactly where a
# list of files is (Sheet source / extra files, strip source), and it means that
# list. ``*`` only (``?`` / ``[`` are literal), in the file name only, matched
# case-sensitively on every OS in the first image-search folder with a match.

def _is_file_pattern(name) -> bool:
    return isinstance(name, str) and "*" in name


def _check_file_pattern(pattern: str) -> None:
    """Refuse pattern forms decided from the string alone (never from disk)."""
    folder, base = os.path.split(pattern)
    if "*" in folder:
        raise ValueError(
            f"File pattern {pattern!r} has * in a folder name. A pattern matches "
            "file names in one folder: put * in the file name only, e.g. "
            '"ninja/Run__*.png".'
        )
    if is_atlas_filename(base):
        raise TypeError(
            f"File pattern {pattern!r} names atlas files. A pattern loads images, "
            "one file per frame; an atlas is one file: "
            'Sheet("sheet.png", atlas="sheet.xml").'
        )


def _natural_key(name: str):
    """``Run (2)`` before ``Run (10)``: digit runs compare as numbers."""
    parts = re.split(r"(\d+)", name)
    return (
        tuple(int(p) if i % 2 else p.casefold() for i, p in enumerate(parts)),
        name,
    )


def _pattern_regex(base: str, flags: int = 0):
    body = "".join(".*" if part == "*" else re.escape(part)
                   for part in re.split(r"(\*)", base))
    return re.compile(body, flags | re.DOTALL)


def _pattern_matches(pattern: str) -> Tuple[List[str], List[str]]:
    """``(files, folders)``: the matches of the first folder that has any, in
    natural order, and every folder searched (the image search order).

    A name starting with ``.`` matches only a pattern starting with ``.``
    (keeps macOS ``._Idle__000.png`` AppleDouble files out of a clip).
    """
    base = os.path.basename(pattern)
    rx = _pattern_regex(base)
    hidden_ok = base.startswith(".")
    folders: List[str] = []
    for cand in _image_candidates(pattern):
        folder = os.path.dirname(cand)
        if folder in folders:
            continue
        folders.append(folder)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        hits = [
            n for n in names
            if rx.fullmatch(n) and (hidden_ok or not n.startswith("."))
            and os.path.isfile(os.path.join(folder, n))
        ]
        if hits:
            hits.sort(key=_natural_key)
            return [os.path.join(folder, n) for n in hits], folders
    return [], folders


def _case_near_misses(pattern: str, folders: Sequence[str]) -> List[str]:
    """File names that match ``pattern`` only when case is ignored."""
    rx = _pattern_regex(os.path.basename(pattern), re.IGNORECASE)
    for folder in folders:
        try:
            names = sorted(os.listdir(folder), key=_natural_key)
        except OSError:
            continue
        hits = [n for n in names if rx.fullmatch(n) and not n.startswith(".")]
        if hits:
            return hits[:3]
    return []


def _expand_pattern(pattern: str) -> List[str]:
    """The matched paths, or ``[pattern]`` (a placeholder frame) after one warning."""
    files, folders = _pattern_matches(pattern)
    if files:
        return files
    if pattern not in _MISSING_WARNED:
        # The pattern string then loads as a missing file: same key, no 2nd warning.
        _MISSING_WARNED.add(pattern)
        near = _case_near_misses(pattern, folders)
        hint = (
            f" Matching is case-sensitive; these differ only in case: {near}."
            if near else ""
        )
        warnings.warn(
            f"No file matches {pattern!r}. Using a placeholder frame. "
            "The clip is still valid. "
            f"Looked in: {'; '.join(folders)}.{hint}",
            RuntimeWarning,
            skip_file_prefixes=_WARN_SKIP,
        )
    return [pattern]


def _expand_file_list(files: Sequence[str]) -> List[str]:
    """Each pattern replaced by its matches, in place; plain names pass through."""
    out: List[str] = []
    for f in files:
        if _is_file_pattern(f):
            out.extend(_expand_pattern(f))
        else:
            out.append(f)
    return out


def _make_placeholder(label: Optional[str] = None) -> skia.Image:
    """Magenta/black checker. Optional filename baked in (once per label)."""
    key = label or ""
    hit = _PLACEHOLDER_CACHE.get(key)
    if hit is not None:
        return hit
    side = _PLACEHOLDER_SIDE
    cell = side // _CHECKER_CELLS
    info = skia.ImageInfo.Make(side, side, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surface = skia.Surface.MakeRaster(info)
    c = surface.getCanvas()
    mag = skia.Paint(Color=_CHECKER_MAGENTA)
    blk = skia.Paint(Color=_CHECKER_BLACK)
    for i in range(_CHECKER_CELLS):
        for j in range(_CHECKER_CELLS):
            c.drawRect(
                skia.Rect.MakeXYWH(i * cell, j * cell, cell, cell),
                mag if (i + j) % 2 == 0 else blk,
            )
    if key:
        paint = skia.Paint(Color=skia.ColorWHITE, AntiAlias=True)
        font = skia.Font(skia.Typeface(""), 9.0)
        text = key if len(key) <= 18 else key[:15] + "..."
        c.drawString(text, 3.0, 12.0, font, paint)
    img = surface.makeImageSnapshot()
    _PLACEHOLDER_CACHE[key] = img
    return img


def _placeholder_for_layout(
    img: skia.Image,
    *,
    cols: Optional[int],
    rows: Optional[int],
    cell: Optional[Tuple[int, int]],
) -> skia.Image:
    """Tile the missing-file checker so the requested grid still divides it.

    A missing ``Sheet("hero.png", cols=4, rows=3)`` keeps its 12 frames (and
    clip indices) instead of failing the layout check on the 64×64 checker.
    """
    if cols is None and rows is None and cell is None:
        return img
    side_w, side_h = int(img.width()), int(img.height())
    if cell is not None:
        w, h = int(cell[0]), int(cell[1])
        n_c = n_r = 1
    else:
        n_c = cols if cols is not None else 1
        n_r = rows if rows is not None else 1
        w, h = side_w, side_h
    info = skia.ImageInfo.Make(
        w * n_c, h * n_r, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType,
    )
    surface = skia.Surface.MakeRaster(info)
    c = surface.getCanvas()
    for i in range(n_c):
        for j in range(n_r):
            c.drawImageRect(img, skia.Rect.MakeXYWH(i * w, j * h, w, h))
    return surface.makeImageSnapshot()


def _decode_image(path: str) -> skia.Image:
    """Decode once; share with Texture's cache when the file is real."""
    key = os.path.abspath(path)
    hit = _IMAGE_CACHE.get(key)
    if hit is not None:
        return hit
    from . import style as _style
    shared = _style._IMAGE_CACHE.get(key)
    if shared is None:
        shared = skia.Image.open(path)
        if shared is None:
            raise ValueError(f"Failed to decode image: {path}")
        # Texture / wallpaper keep the lazy image. setShader of a raster
        # image PNG-encodes (§5.5). Sprite blits want a one-time decode.
        _style._IMAGE_CACHE[key] = shared
        _style._pinnable(shared)
    lazy = getattr(shared, "isLazyGenerated", None)
    raster = shared.makeRasterImage() if callable(lazy) and lazy() else shared
    if raster is None:
        raster = shared
    _IMAGE_CACHE[key] = raster
    _style._pinnable(raster)
    return raster


def _load_sprite_image(source: str) -> Tuple[skia.Image, bool, str]:
    """Return ``(image, is_placeholder, display_name)``. Warns once if missing."""
    resolved = _resolve_image_path(source)
    if resolved is not None:
        try:
            return _decode_image(resolved), False, os.path.basename(resolved)
        except Exception as e:
            warnings.warn(
                f"Sprite failed to decode {source!r} ({e}). Using a placeholder. "
                "The actor is still valid.",
                RuntimeWarning,
                skip_file_prefixes=_WARN_SKIP,
            )
            return _make_placeholder(os.path.basename(source)), True, os.path.basename(source)
    display = os.path.basename(source) or source
    if source not in _MISSING_WARNED:
        _MISSING_WARNED.add(source)
        warnings.warn(
            f"Sprite file not found: {source!r}. Using a placeholder. "
            "The actor is still valid (layer / groups / process still work).",
            RuntimeWarning,
            skip_file_prefixes=_WARN_SKIP,
        )
    return _make_placeholder(display), True, display


# ---------------------------------------------------------------------------
# Sheet (catalog — does not place)
# ---------------------------------------------------------------------------

class Sheet(ClosedSurface):
    """Image catalog: warms the decode cache and holds named frame clips.

    Does **not** place an actor. ``Sprite(sheet, ...)`` instances play clips
    from this catalog. Register clips with ``clip`` (optional ``yoyo=True``
    ping-pong), then ``sprite.play(clip)``. Append another strip file with
    ``strip`` (separate backing image; call during setup).

    Loading modes::

        Sheet("run.png", cols=8, fps=6)               # grid + default clip
        Sheet("hero.png", cols=4, rows=3)             # cols × rows layout
        Sheet("tiles.png", cell=(16, 16))             # pixel cell size
        Sheet("sheet.png", atlas="sheet.json")        # packed JSON / Kenney XML
        Sheet(["Fly (1).png", "Fly (2).png"])         # one image per frame
        Sheet("Fly (1).png", "Fly (2).png")           # same, extra positional files
        Sheet("idle.png", cols=4, fps=6, name="idle") # first strip of a multi-file catalog
        Sheet()                                       # escape: only ``strip`` calls

    Args:
        source: Image file, list of files (one per frame), or omitted.
        cols: Grid columns.
        rows: Grid rows.
        cell: Cell size ``(w, h)`` in image pixels (instead of cols / rows).
        atlas: JSON / XML atlas that goes with the image.
        fps: Register a clip over all frames at this rate.
        name: That clip's name (needs ``fps``; default ``"default"``).
        yoyo: Ping-pong the constructor clip (needs ``fps``).
        anchor: Point of each frame placed at the Sprite center: ``"center"``,
            ``"bottom"``, … or ``(ax, ay)``.
        pixel_size: Design units per image pixel (3 = pixel art at 3×).
    """

    _intern: Dict[tuple, "Sheet"] = {}

    # Registration (``anchor=`` / ``clip(offset=)``). Class defaults so interned
    # sheets built with ``__new__`` read "center, no offsets" (shared frames).
    _anchor = "center"
    _anchor_pivot: Tuple[float, float] = (0.5, 0.5)
    _frame_offsets: Dict[int, Tuple[float, float]] = {}
    _clip_offsets: Dict[str, Tuple[float, float]] = {}    # clip name → its offset=
    _frame_paths: Tuple[Optional[str], ...] = ()           # file each frame came from (or None)
    _path_to_index: Dict[str, int] = {}
    _ambiguous_names: Dict[str, Tuple[int, ...]] = {}
    _plain_frames = True
    _layout_epoch = 0
    _eff_frames: Optional[Tuple[AtlasFrame, ...]] = None
    # ``pixel_size=``: design units per PNG pixel for Sprites of this sheet
    # that pass no size keyword. ``None`` = the per-sprite default size.
    _pixel_size: Optional[float] = None

    def __init__(
        self,
        source: Union[str, Sequence[str], None] = None,
        *more_files: str,
        cols: Optional[int] = None,
        rows: Optional[int] = None,
        cell: Optional[Tuple[int, int]] = None,
        atlas: Optional[str] = None,
        fps: Optional[float] = None,
        name: Optional[str] = None,
        yoyo: bool = False,
        anchor=None,
        pixel_size=None,
    ):
        self._set_anchor(anchor)
        pixel_size = as_payload(pixel_size)
        self._pixel_size = (
            None if pixel_size is None
            else _positive_number(pixel_size, what="pixel_size", exclusive=True)
        )
        files = _collect_file_list(source, more_files)
        patterns = [f for f in files if _is_file_pattern(f)]
        for pattern in patterns:
            _check_file_pattern(pattern)
        per_file = len(files) > 1 or bool(patterns)
        from .atlas import alloc_sheet_token, release_sheet_token
        import weakref
        self._cache_token = alloc_sheet_token()
        weakref.finalize(self, release_sheet_token, self._cache_token)
        self._cycles: Dict[str, Tuple[List[int], float, bool]] = {}
        self._name_to_index: Dict[str, int] = {}
        self._names: Tuple[str, ...] = ()
        self._atlas_frames: Tuple[AtlasFrame, ...] = ()
        self._cols_arg, self._rows_arg = _parse_cols_rows(cols, rows)
        self._cell = _parse_cell(cell)
        self._packed = False
        self._is_atlas = False
        self._missing_atlas = False
        self._shared = False
        self._interned = False
        fps = as_payload(fps)
        name = as_payload(name)
        from .validate import expect_bool
        yoyo = expect_bool(yoyo, "Sheet yoyo")
        _reject_layout_conflicts(
            cols=self._cols_arg,
            rows=self._rows_arg,
            cell=self._cell,
            atlas=atlas,
            multi_file=per_file,
            pattern=patterns[0] if patterns else None,
        )

        if files and atlas is not None and per_file:
            raise TypeError(
                "atlas= is for one packed sheet, not a list of image files. "
                'Write Sheet("sheet.png", atlas="sheet.json") or '
                'Sheet(["a.png", "b.png"]).'
            )
        atlas_mode = atlas is not None or (
            not per_file and len(files) == 1 and is_atlas_filename(files[0])
        )
        self._check_ctor_clip_kwargs(
            fps=fps, name=name, yoyo=yoyo, atlas_mode=atlas_mode,
        )

        if not files and atlas is None:
            self._init_empty()
            self._apply_ctor_clip(fps=fps, name=name, yoyo=yoyo)
            return
        if files and per_file:
            self._init_from_files(_expand_file_list(files), label=files[0])
            self._apply_ctor_clip(fps=fps, name=name, yoyo=yoyo)
            return

        single = files[0] if files else None
        atlas_path = atlas
        image_source = single
        if atlas_path is None and single is not None and is_atlas_filename(single):
            atlas_path = single
            image_source = None
        if atlas_path is not None:
            self._init_from_atlas(image_source, atlas_path)
            self._apply_ctor_clip(fps=fps, name=name, yoyo=yoyo)
            return
        if image_source is None:
            raise TypeError(
                "Sheet expected a filename, a list of filenames, or atlas=. "
                'Write Sheet("hero.png", cols=4, rows=3).'
            )
        self._init_from_image(image_source)
        self._apply_ctor_clip(fps=fps, name=name, yoyo=yoyo)

    def _init_empty(self) -> None:
        """Escape catalog: no pixels yet. Fill with ``strip`` before ``Sprite``."""
        self._source = ""
        self._image = None
        self._placeholder = False
        self._display = ""
        self._packed = False
        self._is_atlas = False
        self._missing_atlas = False
        self._px_w = 1
        self._px_h = 1
        self._cell_w = 1
        self._cell_h = 1
        self._cols = 1
        self._rows = 1
        self._nframes = 0
        self._src = ()
        self._atlas_frames = ()
        self._images = []
        self._frame_image = ()
        self._name_to_index = {}
        self._names = ()

    @staticmethod
    def _check_ctor_clip_kwargs(*, fps, name, yoyo: bool, atlas_mode: bool) -> None:
        if atlas_mode and (fps is not None or name is not None or yoyo):
            raise TypeError(
                "fps=/name=/yoyo= on a packed atlas does not autoplay every "
                "subtexture. Define clips with sheet.clip after load: "
                'sheet.clip("fly", ["fire00.png", "fire01.png"], fps=12).'
            )
        if name is not None and fps is None:
            raise TypeError(
                'name= requires fps= (it names the default clip). '
                'Write Sheet("run.png", cols=8, fps=8, name="walk").'
            )
        if yoyo and fps is None:
            raise TypeError(
                'yoyo= requires fps= (it sets yoyo on the default clip). '
                'Write Sheet("idle.png", cols=4, fps=6, yoyo=True).'
            )

    def _apply_ctor_clip(self, *, fps, name, yoyo: bool) -> None:
        if fps is None:
            return
        if self._nframes < 1:
            raise ValueError(
                "fps= needs at least one frame. Load an image first, or "
                'call strip(...) before Sprite(sheet).'
            )
        clip_name = _parse_clip_name(name)
        self.clip(clip_name, list(range(self._nframes)), fps=fps, yoyo=yoyo)

    def _init_from_image(self, source: str) -> None:
        self._source = source
        self._image, self._placeholder, self._display = _load_sprite_image(source)
        if self._placeholder:
            self._image = _placeholder_for_layout(
                self._image, cols=self._cols_arg, rows=self._rows_arg, cell=self._cell,
            )
            if self._cell is not None and self._cols_arg is None and self._rows_arg is None:
                # ``cell=`` alone: the cell count is the missing file's, unknown.
                # Every index shows the checker, as a missing atlas does, so
                # clips still build (graphics review PA13: "missing stays
                # legal" raised at the first clip past cell 0).
                self._missing_atlas = True
        iw = int(self._image.width())
        ih = int(self._image.height())
        self._px_w = max(1, iw)
        self._px_h = max(1, ih)
        self._cell_w, self._cell_h, self._cols, self._rows, self._nframes = _sheet_layout(
            self._px_w, self._px_h,
            cols=self._cols_arg, rows=self._rows_arg, cell=self._cell,
        )
        self._src: Tuple[skia.Rect, ...] = tuple(
            _cell_src(self._cell_w, self._cell_h, self._cols, i)
            for i in range(self._nframes)
        )
        self._atlas_frames = tuple(
            _grid_frame(i, self._cell_w, self._cell_h, self._cols)
            for i in range(self._nframes)
        )
        self._set_single_image_backing(self._image)
        self._apply_frame_names()

    def _init_placeholder(self, label: str, *, missing_atlas: bool = False) -> None:
        """One-cell magenta checker. Missing atlas catalogs map any frame name here."""
        display = label or "placeholder"
        img = _make_placeholder(display)
        self._source = display
        self._image = img
        self._placeholder = True
        self._display = display
        self._packed = False
        self._is_atlas = False
        self._missing_atlas = bool(missing_atlas)
        self._px_w = max(1, int(img.width()))
        self._px_h = max(1, int(img.height()))
        self._cell_w, self._cell_h, self._cols, self._rows, self._nframes = _sheet_layout(
            self._px_w, self._px_h, cols=None, rows=None, cell=None,
        )
        self._src = tuple(
            _cell_src(self._cell_w, self._cell_h, self._cols, i)
            for i in range(self._nframes)
        )
        self._atlas_frames = tuple(
            _grid_frame(i, self._cell_w, self._cell_h, self._cols)
            for i in range(self._nframes)
        )
        self._set_single_image_backing(self._image)
        self._apply_frame_names()

    def _init_from_atlas(self, image_source: Optional[str], atlas: str) -> None:
        resolved = _resolve_image_path(atlas)
        if resolved is None:
            display = os.path.basename(atlas) or atlas
            if atlas not in _MISSING_WARNED:
                _MISSING_WARNED.add(atlas)
                warnings.warn(
                    f"Atlas file not found: {atlas!r}. Using a placeholder. "
                    "The catalog is still valid (Sprite / clip / play still work). "
                    "Looked next to the script, in that folder's media/, "
                    "and in the current working directory.",
                    RuntimeWarning,
                    skip_file_prefixes=_WARN_SKIP,
                )
            self._init_placeholder(display, missing_atlas=True)
            return
        try:
            listed_image, frames = load_atlas(resolved)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(
                f"Failed to read atlas {atlas!r} ({e}). "
                "JSON (TexturePacker Hash/Array) and Kenney XML are supported."
            ) from e
        if not frames:
            raise ValueError(f"Atlas {atlas!r} has no frames.")
        img_path: Optional[str] = None
        listed_path = _resolve_listed_atlas_image(resolved, listed_image)
        source_miss_warned = False
        if image_source:
            author_path = _resolve_image_path(image_source)
            if author_path is None:
                # Explicit path that was already absolute-missing, or relative miss.
                if os.path.isabs(image_source) and os.path.isfile(image_source):
                    author_path = os.path.abspath(image_source)
            if author_path is not None:
                img_path = author_path
                if listed_path is not None and os.path.abspath(author_path) != os.path.abspath(listed_path):
                    _warn_atlas_source_mismatch(image_source, listed_image)
            else:
                listed_name = listed_image or "(none)"
                warn_key = f"atlas-source-miss:{image_source}"
                if warn_key not in _MISSING_WARNED:
                    _MISSING_WARNED.add(warn_key)
                    if listed_path is not None:
                        warnings.warn(
                            f"source={image_source!r} was not found; atlas lists "
                            f"{listed_name!r} — using the listed image. "
                            "Looked next to the script, in that folder's media/, "
                            "and in the current working directory.",
                            RuntimeWarning,
                            skip_file_prefixes=_WARN_SKIP,
                        )
                    else:
                        warnings.warn(
                            f"source={image_source!r} was not found; atlas lists "
                            f"{listed_name!r}, which was also missing. "
                            "Using a placeholder. The catalog is still valid.",
                            RuntimeWarning,
                            skip_file_prefixes=_WARN_SKIP,
                        )
                source_miss_warned = True
                img_path = listed_path
        else:
            img_path = _resolve_atlas_image(resolved, listed_image)
        if img_path is None:
            display = os.path.basename(image_source or listed_image or atlas)
            self._image, self._placeholder, self._display = (
                _make_placeholder(display), True, display,
            )
            miss_key = image_source or listed_image or atlas
            if not source_miss_warned and miss_key not in _MISSING_WARNED:
                _MISSING_WARNED.add(miss_key)
                warnings.warn(
                    f"Atlas image not found for {atlas!r} "
                    f"(listed {listed_image!r}). Using a placeholder. "
                    "Pass the png: Sheet(\"space_sheet.png\", atlas=\"space_sheet.xml\").",
                    RuntimeWarning,
                    skip_file_prefixes=_WARN_SKIP,
                )
        else:
            self._image, self._placeholder, self._display = _load_sprite_image(img_path)
        self._source = image_source or atlas
        self._packed = True
        self._is_atlas = True
        self._atlas_frames = frames
        self._nframes = len(frames)
        self._src = tuple(fr.packed_rect() for fr in frames)
        self._px_w = max(1, int(self._image.width()))
        self._px_h = max(1, int(self._image.height()))
        # Reference cell = first frame's source size (Sprite size uses the chosen frame).
        self._cell_w = frames[0].src_w
        self._cell_h = frames[0].src_h
        self._cols = self._nframes
        self._rows = 1
        self._set_single_image_backing(self._image)
        self._apply_frame_names()

    def _init_from_files(self, files: List[str], *, label: Optional[str] = None) -> None:
        packed, frames, any_placeholder, display, paths = _pack_frame_files(files)
        self._frame_paths = paths
        self._source = label or files[0]
        self._image = packed
        self._placeholder = any_placeholder
        self._display = display
        self._packed = True
        self._is_atlas = False
        self._atlas_frames = frames
        self._nframes = len(frames)
        self._src = tuple(fr.packed_rect() for fr in frames)
        self._px_w = max(1, int(packed.width()))
        self._px_h = max(1, int(packed.height()))
        self._cell_w = frames[0].src_w
        self._cell_h = frames[0].src_h
        self._cols = self._nframes
        self._rows = 1
        self._set_single_image_backing(self._image)
        self._apply_frame_names()

    def _bind_cache_images(self) -> None:
        from .atlas import bind_sheet_images
        imgs = []
        image = getattr(self, "_image", None)
        if image is not None:
            imgs.append(image)
        for im in getattr(self, "_images", ()) or ():
            if im is not None and all(im is not other for other in imgs):
                imgs.append(im)
        bind_sheet_images(self._cache_token, imgs)

    def _set_single_image_backing(self, image: skia.Image) -> None:
        """One backing image; every frame indexes into it."""
        prev = getattr(self, "_image", None)
        if prev is not None and prev is not image:
            import weakref
            from .atlas import alloc_sheet_token, release_sheet_token
            release_sheet_token(self._cache_token)
            self._cache_token = alloc_sheet_token()
            weakref.finalize(self, release_sheet_token, self._cache_token)
        self._image = image
        self._images: List[skia.Image] = [image]
        self._frame_image: Tuple[int, ...] = tuple(0 for _ in range(self._nframes))
        self._bind_cache_images()

    def _apply_frame_names(self) -> None:
        mapping: Dict[str, int] = {}
        names: List[str] = []
        owners: Dict[str, List[int]] = {}
        for i, fr in enumerate(self._atlas_frames):
            names.append(fr.name)
            owners.setdefault(fr.name, []).append(i)
            mapping[fr.name] = i
            stem, ext = os.path.splitext(fr.name)
            if ext and stem and stem not in mapping:
                mapping[stem] = i
        # Two frames with one name (``idle/1.png`` and ``run/1.png``, both
        # "1"): the name names neither, and the path that loaded each frame
        # still names it. The last one won silently, even for the exact path
        # (graphics review PA3).
        ambiguous = {n: tuple(ix) for n, ix in owners.items() if len(ix) > 1}
        for n in ambiguous:
            mapping.pop(n, None)
            stem, ext = os.path.splitext(n)
            if ext and mapping.get(stem) in ambiguous[n]:
                mapping.pop(stem, None)
        by_path: Dict[str, int] = {}
        for i, path in enumerate(self._frame_paths):
            if path:
                by_path[path] = i
                by_path[os.path.splitext(path)[0]] = i
        self._name_to_index = mapping
        self._ambiguous_names = ambiguous
        self._path_to_index = by_path
        self._names = tuple(names)

    @property
    def image(self) -> skia.Image:
        """Primary (first) backing image. Prefer ``_image_for_frame`` when drawing."""
        return self._image

    def _image_for_frame(self, index: int) -> skia.Image:
        """Backing image for a frame index (``strip`` may append more images)."""
        n = self._nframes
        i = int(index) % n if n else 0
        images = getattr(self, "_images", None)
        if not images:
            return self._image
        fi = getattr(self, "_frame_image", ())
        img_i = fi[i] if i < len(fi) else 0
        return images[img_i]

    @property
    def nframes(self) -> int:
        """How many frames the sheet has. Read-only."""
        return self._nframes

    @property
    def names(self) -> Tuple[str, ...]:
        """Frame names in sheet order (packed atlas / multi-file). Empty-ish for a grid."""
        return self._names

    def frame_index(self, key: Union[int, str]) -> int:
        """Resolve a cell index or atlas frame name."""
        key = as_payload(key)
        if isinstance(key, bool) or not isinstance(key, (int, str)):
            raise TypeError(
                f"frame expected an int index or a name string, got {type(key).__name__}. "
                'Write frame=0 or frame="playerShip1_blue.png".'
            )
        if isinstance(key, int):
            # An empty sheet has no cell to name (PA4: any index passed and the
            # draw wrapped it ``% n`` once strip filled the sheet).
            if key < 0 or key >= self._nframes:
                if getattr(self, "_missing_atlas", False):
                    return 0
                if not self._nframes:
                    raise ValueError(
                        f"frame={key}: this sheet has no cells yet. Load them first: "
                        'Sheet("hero.png", cols=4), or sheet.strip(...).'
                    )
                raise ValueError(
                    f"frame={key} is out of range (0..{self._nframes - 1}; "
                    f"this sheet has {self._nframes} cells)."
                )
            return key
        hit = self._name_to_index.get(key)
        if hit is None:
            hit = self._path_to_index.get(key)      # the string that loaded the frame
            if hit is None and ("/" in key or os.sep in key) and self._path_to_index:
                # A tail of that path ("idle/1.png"): it names one frame or none.
                tail = os.sep + os.path.normpath(key).lstrip(os.sep)
                found = {i for p, i in self._path_to_index.items()
                         if os.path.normpath(p).endswith(tail)}
                if len(found) == 1:
                    hit = found.pop()
        if hit is None:
            # Suffix match: "blue.png" vs "playerShip1_blue.png" is too loose;
            # try with a common extension.
            for ext in (".png", ".jpg", ".jpeg"):
                hit = self._name_to_index.get(key + ext)
                if hit is not None:
                    break
        if hit is None:
            # Same strings used to load a multi-file sheet: path or "Idle__000.png".
            base = os.path.basename(key)
            if base != key:
                hit = self._name_to_index.get(base)
            if hit is None:
                stem, ext = os.path.splitext(base)
                if stem and stem != base:
                    hit = self._name_to_index.get(stem)
        if hit is None:
            if getattr(self, "_missing_atlas", False):
                return 0
            base = os.path.basename(key)
            for name in (key, base, os.path.splitext(base)[0]):
                twins = self._ambiguous_names.get(name)
                if twins:
                    files = [self._frame_paths[i] for i in twins if i < len(self._frame_paths)]
                    shown = ", ".join(repr(f) for f in files if f) or ", ".join(map(str, twins))
                    raise ValueError(
                        f"frame {key!r} names {len(twins)} frames ({shown}). "
                        "Write the path that loaded the one you mean, or its index."
                    )
            raise ValueError(self._unknown_frame_message(key))
        return hit

    def _unknown_frame_message(self, key: str) -> str:
        n = self._nframes
        sample = ", ".join(repr(n_) for n_ in self._names[:8])
        extra = f" … ({n} frames)" if n > 8 else ""
        available = sample + extra if sample else "(this sheet has no named frames — use an int index)"
        return (
            f"Unknown frame {key!r}. Available: {available}. "
            f'Write Sprite(sheet, frame="playerShip1_blue.png") or sheet.names.'
        )

    def _refuse_interned_mutation(self, verb: str) -> None:
        if not getattr(self, "_interned", False):
            return
        raise TypeError(
            f"sheet.{verb}() cannot mutate an interned still shared by "
            'Sprite("file.png"). Build a catalog first: '
            'Sheet("idle.png", cols=4, fps=6, name="idle") then '
            'sheet.strip("walk", "walk.png", cols=8, fps=12).'
        )

    def clip(
        self,
        name: str,
        frames: Optional[Sequence[Union[int, str]]] = None,
        *,
        fps: float = 8.0,
        yoyo: bool = False,
        offset=None,
    ) -> "Sheet":
        """Register a named clip from cells already on the sheet.

        Omit ``frames`` to use every cell loaded so far (``range(nframes)``).
        ``yoyo=False`` wraps (``0→1→2→0→…``); ``yoyo=True`` ping-pongs.
        ``frames`` are indices or atlas names. ``offset=(dx, dy)`` moves this
        clip's art by art pixels (y-up; mirrors with ``flip_x`` / ``flip_y``) —
        the escape path when a pack's cells do not line up.
        """
        self._refuse_interned_mutation("clip")
        if frames is None:
            if self._nframes < 1:
                raise ValueError(
                    f"Sheet.clip({name!r}) has no frames yet. "
                    "Load an image (or strip) first, or pass frames= explicitly."
                )
            frames = list(range(self._nframes))
        return self._register_clip(
            name, frames, fps=fps, yoyo=as_payload(yoyo), offset=offset,
        )

    def strip(
        self,
        name: str,
        source: Union[str, Sequence[str]],
        *,
        cols: Optional[int] = None,
        rows: Optional[int] = None,
        cell: Optional[Tuple[int, int]] = None,
        fps: float = 8.0,
        yoyo: bool = False,
        offset=None,
    ) -> "Sheet":
        """Append frames from more files and register them as a named clip.

        ``source`` is one image (a grid with ``cols=`` / ``rows=`` / ``cell=``,
        or one frame), a file pattern (``"ninja/Run__*.png"``: every matching
        file, natural order, one frame each), or a list of files (one frame
        each). Does **not** repack existing frames — each call is a separate
        backing image. Call during setup (not every frame). Name-first, like
        ``clip``.
        """
        self._refuse_interned_mutation("strip")
        name = as_payload(name)
        source = as_payload(source)
        if not isinstance(name, str) or not name:
            raise TypeError(
                'strip name is required. '
                'Write sheet.strip("idle", "idle.png", cols=4, fps=6).'
            )
        files = _strip_file_list(source)
        patterns = [f for f in files if _is_file_pattern(f)]
        for pattern in patterns:
            _check_file_pattern(pattern)
        if any(is_atlas_filename(f) for f in files):
            raise TypeError(
                "strip does not load packed atlases. "
                'Write Sheet("sheet.png", atlas="sheet.json") for atlas art, '
                "or pass a strip / single-frame png to strip."
            )
        per_file = len(files) > 1 or bool(patterns)
        from .validate import expect_bool
        yoyo_mode = expect_bool(yoyo, "Sheet yoyo")
        fps_v = _positive_number(as_payload(fps), what="fps")
        # Every clip argument before the frames are appended (PA5: a bad
        # offset raised after the new cells were already on the sheet).
        _parse_clip_offset(offset)
        cols_arg, rows_arg = _parse_cols_rows(cols, rows)
        cell_arg = _parse_cell(cell)
        _reject_layout_conflicts(
            cols=cols_arg, rows=rows_arg, cell=cell_arg,
            atlas=None, multi_file=per_file,
            pattern=patterns[0] if patterns else None, verb="strip",
        )

        if per_file:
            img, new_frames, placeholder, display, new_paths = _pack_frame_files(
                _expand_file_list(files),
            )
            new_src = tuple(fr.packed_rect() for fr in new_frames)
            ncols, nrows = len(new_frames), 1
        else:
            img, placeholder, display = _load_sprite_image(files[0])
            if placeholder:
                img = _placeholder_for_layout(img, cols=cols_arg, rows=rows_arg, cell=cell_arg)
            cell_w, cell_h, ncols, nrows, n_grid = _sheet_layout(
                max(1, int(img.width())), max(1, int(img.height())),
                cols=cols_arg, rows=rows_arg, cell=cell_arg,
            )
            if n_grid < 1:
                raise ValueError(
                    f"strip({files[0]!r}) produced no frames. "
                    'Check cols=/rows=/cell= against the image size.'
                )
            new_frames = tuple(
                AtlasFrame(
                    f"{name}:{i}",
                    (i % ncols) * cell_w,
                    (i // ncols) * cell_h,
                    cell_w,
                    cell_h,
                )
                for i in range(n_grid)
            )
            new_src = tuple(
                _cell_src(cell_w, cell_h, ncols, i) for i in range(n_grid)
            )
            new_paths = (None,) * n_grid
        n_new = len(new_frames)
        iw = max(1, int(img.width()))
        ih = max(1, int(img.height()))

        if not getattr(self, "_images", None):
            self._images = []
            self._frame_image = ()
            self._src = ()
            self._atlas_frames = ()
            self._frame_paths = ()
            self._nframes = 0
            self._image = img
            self._source = files[0]
            self._display = display
            self._px_w = iw
            self._px_h = ih
            self._cell_w = new_frames[0].src_w
            self._cell_h = new_frames[0].src_h
            self._cols = ncols
            self._rows = nrows

        img_index = len(self._images)
        self._images.append(img)
        self._bind_cache_images()
        self._placeholder = bool(self._placeholder) or bool(placeholder)

        base = self._nframes
        old_paths = tuple(self._frame_paths)[:base]
        self._frame_paths = old_paths + (None,) * (base - len(old_paths)) + tuple(new_paths)
        self._atlas_frames = self._atlas_frames + new_frames
        self._src = self._src + new_src
        self._frame_image = self._frame_image + tuple(img_index for _ in range(n_new))
        self._nframes = base + n_new
        self._apply_frame_names()

        indices = list(range(base, base + n_new))
        self._refresh_frame_views()
        self._register_clip(name, indices, fps=fps_v, yoyo=yoyo_mode, offset=offset)
        return self

    def _register_clip(
        self,
        name: str,
        frames: Sequence[Union[int, str]],
        *,
        fps: float,
        yoyo: bool,
        offset=None,
    ) -> "Sheet":
        name = as_payload(name)
        fps = as_payload(fps)
        from .validate import expect_bool
        yoyo = expect_bool(yoyo, f"Sheet.clip({name!r}) yoyo")
        off = _parse_clip_offset(offset)
        if not isinstance(name, str) or not name:
            raise TypeError("Sheet.clip name must be a non-empty string")
        fps_v = _positive_number(fps, what="fps")
        if not isinstance(frames, Sequence) or isinstance(frames, (str, bytes)):
            raise TypeError(
                "Sheet.clip frames expected a sequence of int indices or name strings, "
                f"got {type(frames).__name__}"
            )
        if len(frames) == 0:
            raise ValueError(
                f"Sheet.clip({name!r}) frames is empty. "
                'Pass cell indices, e.g. clip("idle", [0, 1, 2], fps=6).'
            )
        out: List[int] = []
        for i, f in enumerate(frames):
            try:
                out.append(self.frame_index(f))
            except (TypeError, ValueError) as e:
                raise type(e)(
                    f"Sheet.clip({name!r}) frames[{i}]={f!r}: {e}"
                ) from e
        # Cell offsets come from the clips that set one, the clip being
        # replaced left out: re-registering "a" clashed with its own old
        # offset, or kept it after offset= was dropped (graphics review PA6).
        offsets: Dict[int, Tuple[float, float]] = {}
        for other, o in self._clip_offsets.items():
            if other != name and other in self._cycles:
                for idx in self._cycles[other][0]:
                    offsets[idx] = o
        if off is not None:
            # An offset is a property of the cell's art: one cell cannot sit
            # in two places. Same offset in two clips is fine.
            for idx in out:
                prev = offsets.get(idx)
                if prev is not None and prev != off:
                    raise ValueError(
                        f"Sheet.clip({name!r}) offset={off} for cell {idx}, which "
                        f"another clip already moved by offset={prev}. A cell has "
                        "one offset; give the clips separate cells."
                    )
            for idx in out:
                offsets[idx] = off
        clip_offsets = {n: o for n, o in self._clip_offsets.items() if n != name}
        if off is not None:
            clip_offsets[name] = off
        self._clip_offsets = clip_offsets
        if offsets != self._frame_offsets:
            self._frame_offsets = offsets
            self._refresh_frame_views()
        if name in self._cycles:
            old_yoyo = self._cycles[name][2]
            warnings.warn(
                f"Sheet clip {name!r} replaced (yoyo={old_yoyo} → yoyo={yoyo}). "
                "Use a new name, or overwrite intentionally.",
                RuntimeWarning,
                skip_file_prefixes=_WARN_SKIP,
            )
        self._cycles[name] = (out, fps_v, yoyo)
        self._selector_cache = None   # ``showing()`` sets name clips
        return self

    def _require_cycle(self, name: str) -> Tuple[List[int], float, bool]:
        name = as_payload(name)
        hit = self._cycles.get(name)
        if hit is not None:
            return hit
        available = ", ".join(repr(n) for n in self._cycles) or "(none — call sheet.clip first)"
        raise ValueError(
            f"Unknown clip {name!r}. Available: {available}. "
            f"Write sheet.clip({name!r}, [0, 1, …], fps=8) "
            f"then sprite.play({name!r})."
        )

    def _src_rect(self, index: int) -> skia.Rect:
        i = int(index) % self._nframes if self._nframes else 0
        return self._src[i]

    def _frame_at(self, index: int) -> AtlasFrame:
        """Cell ``index`` with its resolved pivot (see ``anchor=`` / ``offset=``).

        Default sheets (centre anchor, no offsets) return the shared atlas
        frames. Otherwise a per-Sheet view: authored atlas pivot, else the
        anchor, then the clip offset. Every pivot reader (blit, hitbox bake and
        union, flip, tilt, parts) goes through here.
        """
        i = int(index) % self._nframes if self._nframes else 0
        if self._plain_frames:
            return self._atlas_frames[i]
        eff = self._eff_frames
        if eff is None or len(eff) != len(self._atlas_frames):
            eff = self._eff_frames = tuple(
                self._resolve_frame(j, fr) for j, fr in enumerate(self._atlas_frames)
            )
        return eff[i]

    def _resolve_frame(self, index: int, fr: AtlasFrame) -> AtlasFrame:
        if fr.pivot_authored:
            px, py = float(fr.pivot_x), float(fr.pivot_y)
        else:
            px, py = self._anchor_pivot
        off = self._frame_offsets.get(index)
        if off is not None:
            # Offset is y-up art pixels; the pivot is a y-down source fraction.
            # Art right by dx → the pivot sits dx further left in the art.
            px -= float(off[0]) / float(fr.src_w or 1)
            py += float(off[1]) / float(fr.src_h or 1)
        if px == float(fr.pivot_x) and py == float(fr.pivot_y):
            return fr
        return fr.with_pivot(px, py)

    def _set_anchor(self, anchor) -> None:
        """Default pivot for cells without an authored one (``Sheet(anchor=)``)."""
        parsed = _parse_hitbox_anchor(anchor, what="anchor")
        ax, ay = _anchor_pair(parsed)
        self._anchor = parsed
        # y-up local pair → y-down source fraction (``(0, -1)`` bottom → py 1).
        self._anchor_pivot = (0.5 + 0.5 * ax, 0.5 - 0.5 * ay)
        self._frame_offsets = {}
        self._clip_offsets = {}
        self._refresh_frame_views()

    def _refresh_frame_views(self) -> None:
        self._eff_frames = None
        self._plain_frames = self._anchor_pivot == (0.5, 0.5) and not self._frame_offsets
        # Pivots may have moved (anchor / clip offset): sprites' cached source
        # rects compare this before reuse (PB11).
        self._layout_epoch = getattr(self, "_layout_epoch", 0) + 1

    @property
    def anchor(self):
        """Registration point of cells without an authored pivot (read-only)."""
        return self._anchor

    @property
    def pixel_size(self) -> Optional[float]:
        """Design units per PNG pixel (``Sheet(pixel_size=)``), or ``None`` (read-only).

        Sprites of this sheet that pass no ``height=`` / ``width=`` / ``size=``
        / ``box=`` draw every cell at its PNG size × ``pixel_size``. An explicit
        size on a Sprite still wins for that sprite.
        """
        return self._pixel_size


def _collect_file_list(
    source: Union[str, Sequence[str], None],
    more_files: Sequence[str],
) -> List[str]:
    if isinstance(source, str) and not source.strip():
        raise ValueError(
            "source= is an empty file name. Write Sprite(\"hero.png\"), or "
            "Sprite() for a placeholder."
        )
    if (
        source is not None
        and not isinstance(source, str)
        and isinstance(source, Sequence)
        and not isinstance(source, (bytes, bytearray))
        and more_files
    ):
        raise TypeError(
            "Sheet(source=[...]) cannot take extra positional filenames. "
            "Put every file in the list, or write Sheet(\"a.png\", \"b.png\")."
        )
    files: List[str] = []
    if source is None:
        pass
    elif isinstance(source, str):
        if source:
            files.append(source)
    elif isinstance(source, Sequence) and not isinstance(source, (bytes, bytearray)):
        for i, item in enumerate(source):
            if not isinstance(item, str) or not item:
                raise TypeError(
                    f"Sheet file list[{i}] expected a filename string, "
                    f"got {type(item).__name__}. Write Sheet([\"a.png\", \"b.png\"])."
                )
            files.append(item)
        if not files:
            raise ValueError(
                "file list is empty. Write Sheet([\"Fly (1).png\", \"Fly (2).png\"])."
            )
    else:
        raise TypeError(
            "Sheet expected a filename, a list of filenames, or atlas=. "
            f"got {type(source).__name__}. Write Sheet(\"hero.png\", cols=4, rows=3)."
        )
    for i, item in enumerate(more_files):
        if not isinstance(item, str) or not item:
            raise TypeError(
                f"extra file argument[{i}] expected a filename string, "
                f"got {type(item).__name__}. Write Sheet(\"Fly (1).png\", \"Fly (2).png\")."
            )
        files.append(item)
    return files


def _strip_file_list(source) -> List[str]:
    """``strip`` source → file names: one string (image or pattern) or a list."""
    if isinstance(source, str) and source:
        return [source]
    if isinstance(source, (list, tuple)):
        files: List[str] = []
        for i, item in enumerate(source):
            item = as_payload(item)
            if not isinstance(item, str) or not item:
                raise TypeError(
                    f"strip file list[{i}] expected a filename string, got "
                    f"{type(item).__name__}. "
                    'Write sheet.strip("idle", ["idle_0.png", "idle_1.png"], fps=6).'
                )
            files.append(item)
        if not files:
            raise ValueError(
                "strip file list is empty. "
                'Write sheet.strip("idle", ["idle_0.png", "idle_1.png"], fps=6).'
            )
        return files
    raise TypeError(
        "strip source expected a filename, a file pattern, or a list of files. "
        'Write sheet.strip("idle", "idle.png", cols=4, fps=6) or '
        'sheet.strip("run", "ninja/Run__*.png", fps=12).'
    )


def _pack_frame_files(
    files: Sequence[str],
) -> Tuple[skia.Image, Tuple[AtlasFrame, ...], bool, str]:
    """One file per frame, packed left to right (each keeps its pixel size).

    Returns ``(image, frames, any_placeholder, display)``; frames are named by
    file stem (``"Idle__003"``), so ``clip`` / ``frame=`` can name them.
    """
    images: List[skia.Image] = []
    names: List[str] = []
    any_placeholder = False
    for f in files:
        img, placeholder, display = _load_sprite_image(f)
        images.append(img)
        names.append(os.path.splitext(os.path.basename(f))[0] or display)
        any_placeholder = any_placeholder or placeholder
    # The decoded images are shared (``_IMAGE_CACHE``); share the strip packed
    # from them too. The same strip is the same image to the bake caches, so a
    # second Sheet over the same files reuses the auto-hitbox fits instead of
    # re-fitting them (graphics review PA-note: about 10 ms per instance). The
    # Sheet itself stays the author's own (clip / strip still work).
    key = (tuple(id(im) for im in images), tuple(names))
    hit = _PACK_CACHE.get(key)
    if hit is None:
        hit = compose_strip(images, names)
        _PACK_CACHE[key] = hit
    packed, frames = hit
    display = names[0] if len(names) == 1 else f"{names[0]}+{len(names) - 1}"
    return packed, frames, any_placeholder, display, tuple(files)


def _resolve_atlas_image(atlas_path: str, listed: Optional[str]) -> Optional[str]:
    """Find the png/jpeg next to the atlas, or the name listed inside it."""
    atlas_dir = os.path.dirname(os.path.abspath(atlas_path))
    stem, _ = os.path.splitext(atlas_path)
    candidates: List[str] = []
    if listed:
        candidates.extend([
            listed,
            os.path.join(atlas_dir, listed),
            os.path.join(atlas_dir, os.path.basename(listed)),
        ])
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        candidates.append(stem + ext)
    seen = set()
    for p in candidates:
        if not p:
            continue
        hit = _resolve_image_path(p)
        if hit is not None:
            return hit
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
    return None


def _resolve_listed_atlas_image(atlas_path: str, listed: Optional[str]) -> Optional[str]:
    """Resolve the PNG named inside atlas metadata (no atlas-stem fallback)."""
    if not listed:
        return None
    atlas_dir = os.path.dirname(os.path.abspath(atlas_path))
    candidates = [
        listed,
        os.path.join(atlas_dir, listed),
        os.path.join(atlas_dir, os.path.basename(listed)),
    ]
    seen = set()
    for p in candidates:
        if not p:
            continue
        hit = _resolve_image_path(p)
        if hit is not None:
            return hit
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        if os.path.isfile(ap):
            return ap
    return None


def _warn_stale_hitbox_from(sprite) -> None:
    """Once per sprite: ``hitbox_from`` no longer resolves on this sheet."""
    spec = getattr(sprite, "_hitbox_from", None)
    key = (id(sprite), spec)
    if key in _STALE_HITBOX_WARNED:
        return
    _STALE_HITBOX_WARNED.add(key)
    warnings.warn(
        f"hitbox source={spec!r} is not on this sheet; baking the construct frame.",
        RuntimeWarning,
        skip_file_prefixes=_WARN_SKIP,
    )


def _warn_atlas_source_mismatch(source: str, listed: Optional[str]) -> None:
    """Once-per-asset: author ``source=`` disagrees with the atlas listing."""
    key = f"atlas-mismatch:{source}:{listed}"
    if key in _MISSING_WARNED:
        return
    _MISSING_WARNED.add(key)
    warnings.warn(
        f"source={source!r} but atlas lists {listed!r}; using source.",
        RuntimeWarning,
        skip_file_prefixes=_WARN_SKIP,
    )


def _grid_frame(index: int, cell_w: int, cell_h: int, cols: int) -> AtlasFrame:
    col = index % cols
    row = index // cols
    return AtlasFrame(str(index), col * cell_w, row * cell_h, cell_w, cell_h)


def _parse_positive_int(value, *, what: str) -> int:
    value = as_payload(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{what} expected a positive int, got {type(value).__name__}. "
            f"Write {what}=8."
        )
    if not math.isfinite(value):
        raise ValueError(f"{what} must be a finite whole number, got {value!r}.")
    n = int(value)
    if n != value:
        raise TypeError(f"{what} expected a whole number, got {value!r}.")
    if n < 1:
        raise ValueError(f"{what} must be >= 1, got {n}.")
    return n


def _parse_cols_rows(
    cols: Optional[int],
    rows: Optional[int],
) -> Tuple[Optional[int], Optional[int]]:
    cols = as_payload(cols)
    rows = as_payload(rows)
    c = _parse_positive_int(cols, what="cols") if cols is not None else None
    r = _parse_positive_int(rows, what="rows") if rows is not None else None
    if r is not None and c is None:
        raise TypeError(
            "rows= needs cols= (use cols=1 for a vertical strip). "
            "Write Sheet(\"strip.png\", cols=1, rows=8) or "
            "Sheet(\"run.png\", cols=8)."
        )
    return c, r


def _parse_cell(cell) -> Optional[Tuple[int, int]]:
    cell = as_payload(cell)
    if cell is None:
        return None
    if not isinstance(cell, (tuple, list)) or len(cell) != 2:
        raise TypeError(
            "cell expected a (cell_width, cell_height) pair of pixel sizes, "
            f"got {type(cell).__name__}. Write cell=(32, 32)."
        )
    cw, ch = as_payload(cell[0]), as_payload(cell[1])
    if (
        isinstance(cw, bool) or isinstance(ch, bool)
        or not isinstance(cw, (int, float))
        or not isinstance(ch, (int, float))
    ):
        raise TypeError("cell sizes must be numbers of pixels, e.g. cell=(32, 32).")
    for v in (cw, ch):
        # Whole pixels (32 or 32.0): 16.9 truncated to 16, NaN leaked Python's
        # "cannot convert" (graphics review PA10).
        if isinstance(v, float) and (not math.isfinite(v) or v != int(v)):
            raise ValueError(f"cell sizes must be whole numbers of pixels, got cell=({cw}, {ch}).")
    cw_i, ch_i = int(cw), int(ch)
    if cw_i <= 0 or ch_i <= 0:
        raise ValueError(f"cell sizes must be > 0, got cell=({cw}, {ch}).")
    return (cw_i, ch_i)


def _has_layout(*, cols, rows, cell) -> bool:
    return cols is not None or rows is not None or cell is not None


def _reject_layout_conflicts(
    *,
    cols,
    rows,
    cell,
    atlas=None,
    multi_file: bool = False,
    pattern: Optional[str] = None,
    verb: str = "Sheet",
) -> None:
    layout = _has_layout(cols=cols, rows=rows, cell=cell)
    if cell is not None and (cols is not None or rows is not None):
        raise TypeError(
            "cols=/rows= and cell= cannot be combined. "
            "cols=/rows= arrange the sheet by count; cell=(w, h) is pixel cell size. "
            'Write Sheet("hero.png", cols=4, rows=3) or Sheet("tiles.png", cell=(16, 16)).'
        )
    if layout and atlas is not None:
        raise TypeError(
            "cols=/rows=/cell= and atlas= cannot be combined. "
            "cols=/rows=/cell= is a uniform sheet; atlas= is packed JSON/XML. "
            'Write Sheet("hero.png", cols=4, rows=3) or '
            'Sheet("sheet.png", atlas="sheet.json").'
        )
    if layout and pattern is not None:
        raise TypeError(
            f"cols=/rows=/cell= cannot combine with the file pattern {pattern!r}: "
            "a pattern loads one file per frame, so there is no image to cut. "
            "Drop cols=/rows=/cell=. For one image cut into cells write "
            'sheet.strip("walk", "walk.png", cols=8, fps=12).'
        )
    if layout and multi_file and verb == "strip":
        raise TypeError(
            "cols=/rows=/cell= cannot combine with several files: a list "
            "loads one file per frame, so there is no image to cut. "
            "Drop cols=/rows=/cell=, or pass one image: "
            'sheet.strip("walk", "walk.png", cols=8, fps=12).'
        )
    if layout and multi_file:
        raise TypeError(
            "cols=/rows=/cell= cannot combine with several files. "
            "Sheet([...]) is one file per frame. "
            "For several strip files write "
            'Sheet("idle.png", cols=4, fps=6, name="idle") then '
            'sheet.strip("walk", "walk.png", cols=8, fps=12).'
        )


def _sheet_layout(
    px_w: int,
    px_h: int,
    *,
    cols: Optional[int],
    rows: Optional[int],
    cell: Optional[Tuple[int, int]],
) -> Tuple[int, int, int, int, int]:
    """Return ``(cell_w, cell_h, cols, rows, nframes)``."""
    if cell is not None:
        cw, ch = cell
        if px_w % cw != 0 or px_h % ch != 0:
            raise ValueError(
                f"cell=({cw}, {ch}) does not divide the {px_w}×{px_h} image evenly "
                f"(remainder {px_w % cw}×{px_h % ch} px). "
                "Use a cell size that tiles the sheet, or cols=/rows= instead."
            )
        n_cols = px_w // cw
        n_rows = px_h // ch
        n = n_cols * n_rows
        if n > _MAX_GRID_CELLS:
            raise ValueError(
                f"cell=({cw}, {ch}) would create {n} cells on a {px_w}×{px_h} image "
                f"(max {_MAX_GRID_CELLS}). "
                f"If you meant columns×rows, write cols={cw}, rows={ch} "
                f"(cell size would be {px_w // max(cw, 1)}×{px_h // max(ch, 1)} px)."
            )
        if n < 1:
            return px_w, px_h, 1, 1, 1
        return cw, ch, n_cols, n_rows, n

    if cols is not None:
        n_cols = cols
        n_rows = rows if rows is not None else 1
        if px_w % n_cols != 0 or px_h % n_rows != 0:
            raise ValueError(
                f"cols={n_cols}, rows={n_rows} does not divide the {px_w}×{px_h} image "
                f"evenly (cell would be {px_w / n_cols:g}×{px_h / n_rows:g} px). "
                "Pick counts that tile the sheet, or pass cell=(w, h) in pixels."
            )
        cw = px_w // n_cols
        ch = px_h // n_rows
        n = n_cols * n_rows
        if n > _MAX_GRID_CELLS:
            raise ValueError(
                f"cols={n_cols}, rows={n_rows} would create {n} cells "
                f"(max {_MAX_GRID_CELLS})."
            )
        return cw, ch, n_cols, n_rows, n

    return px_w, px_h, 1, 1, 1


def _cell_src(cell_w: int, cell_h: int, cols: int, index: int) -> skia.Rect:
    col = index % cols
    row = index // cols
    return skia.Rect.MakeXYWH(col * cell_w, row * cell_h, cell_w, cell_h)


def _default_size() -> float:
    try:
        from .canvas import ScenaCanvas
        canvas = ScenaCanvas.get_current()
        unit = _DEFAULT_EXTENT_FRAC * min(float(canvas.width), float(canvas.height))
    except Exception:
        unit = 48.0
    return max(48.0, unit)


def _parse_hitbox(hitbox, what: str = "hitbox_shape") -> str:
    """Return the hitbox shape. Numbers are rejected — a margin is ``scale``.

    ``what`` names the knob as the author wrote it: ``hitbox_shape`` on the
    Sprite constructor, ``shape`` on ``add_hitbox`` / ``hitbox.shape``.
    """
    hitbox = as_payload(hitbox)
    scale = "hitbox_scale" if what.startswith("hitbox_") else "scale"
    if hitbox is None:
        return "auto"
    if isinstance(hitbox, str):
        key = hitbox.strip().lower()
        if key in _HITBOX_CHOICES:
            return key
        raise ValueError(
            f"{what}={hitbox!r}; expected one of "
            f'{", ".join(repr(c) for c in _HITBOX_CHOICES)}. '
            f"For a margin, use {scale}= (e.g. {what}=\"rect\", {scale}=0.9)."
        )
    if isinstance(hitbox, (int, float)) and not isinstance(hitbox, bool):
        raise TypeError(
            f"{what}={hitbox!r} is not a shape; for a margin use "
            f'{what}="rect", {scale}={float(hitbox)} '
            f'(shapes: {", ".join(repr(c) for c in _HITBOX_CHOICES)}).'
        )
    raise TypeError(
        f"{what} expected "
        f'{", ".join(repr(c) for c in _HITBOX_CHOICES)}, '
        f"got {type(hitbox).__name__}"
    )


def _hitbox_from_unknown(sheet, value, what: str = "hitbox_source") -> ValueError:
    clips = ", ".join(repr(n) for n in sheet._cycles) or "(none)"
    names = ", ".join(repr(n) for n in sheet.names[:8])
    extra = f" … ({sheet.nframes} frames)" if sheet.nframes > 8 else ""
    available = names + extra if names else "(unnamed cells — use an int index)"
    return ValueError(
        f"{what}={value!r}; expected {_HITBOX_FROM_EXPECT}. "
        f"Clips: {clips}. Frames: {available}."
    )


_SHOWING_EXPECT = (
    "a clip name, a frame index, a frame name, or a tuple / list of those"
)


def _showing_unknown(sheet, value) -> ValueError:
    clips = ", ".join(repr(n) for n in sheet._cycles) or "(none)"
    names = ", ".join(repr(n) for n in sheet.names[:8])
    extra = f" … ({sheet.nframes} frames)" if sheet.nframes > 8 else ""
    available = names + extra if names else "(unnamed cells — use an int index)"
    return ValueError(
        f"showing({value!r}); expected {_SHOWING_EXPECT}. "
        f"Clips: {clips}. Frames: {available}."
    )


def _selector_cells(item, sheet, whole) -> Tuple[int, ...]:
    """Cells named by one selector atom (clip name wins over a frame name)."""
    item = as_payload(item)
    if isinstance(item, bool) or not isinstance(item, (int, str)):
        raise TypeError(
            f"showing() expected {_SHOWING_EXPECT}; got {type(item).__name__}."
        )
    if isinstance(item, int):
        try:
            return (sheet.frame_index(item),)
        except (TypeError, ValueError):
            raise _showing_unknown(sheet, whole) from None
    key = item.strip()
    if not key:
        raise ValueError(f'showing(""); expected {_SHOWING_EXPECT}.')
    if key.lower() in _HITBOX_FROM_SPECIAL and key not in sheet._cycles:
        raise ValueError(
            f"showing({item!r}): {key!r} is a hitbox_from bake mode, not a frame. "
            "Name a clip, a frame index, or a frame name."
        )
    hit = sheet._cycles.get(key)
    if hit is not None:
        return tuple(int(i) for i in hit[0])
    try:
        return (sheet.frame_index(key),)
    except (TypeError, ValueError):
        raise _showing_unknown(sheet, whole) from None


def _parse_frame_selector(value, sheet) -> frozenset:
    """``showing()`` selector → the set of cell indices it names (cached per sheet)."""
    value = as_payload(value)
    # Cached by exact atom type: ``True == 1 == 1.0`` share a hash, so
    # ``showing(True)`` hit ``showing(1)``'s entry and skipped the type check
    # (graphics review PA7). Anything else parses (and refuses) every time.
    t = type(value)
    if t is str or t is int:
        key = value
    elif (t is tuple or t is list) and all(type(v) is str or type(v) is int for v in value):
        key = ("seq", tuple(value))
    else:
        key = None
    try:
        cache = sheet._selector_cache
    except AttributeError:
        cache = None
    if cache is not None and key is not None:
        try:
            hit = cache.get(key)
        except TypeError:   # unhashable atom inside: parse (and raise) below
            hit = None
        if hit is not None:
            return hit
    if isinstance(value, (tuple, list)):
        if len(value) == 0:
            raise ValueError(f"showing(()) is empty; expected {_SHOWING_EXPECT}.")
        cells: set = set()
        for item in value:
            cells.update(_selector_cells(item, sheet, value))
        out = frozenset(cells)
    else:
        out = frozenset(_selector_cells(value, sheet, value))
    if key is None:
        return out
    if cache is None:
        cache = {}
        sheet._selector_cache = cache
    cache[key] = out
    return out


def _parse_hitbox_from(value, sheet, *, construct_frame: int, what: str = "hitbox_source"):
    """Return a stored hitbox ``source`` spec (``_hitbox_from`` inside).

    ``"all"`` / ``"each"`` / ``"clip"``, a clip name, a frame index, or a tuple
    of clip names. ``None`` (omitted) resolves to the construct frame index.
    """
    value = as_payload(value)
    if value is None:
        return int(construct_frame)
    if isinstance(value, bool):
        raise TypeError(f"{what} expected {_HITBOX_FROM_EXPECT}; got bool.")
    if isinstance(value, int):
        return sheet.frame_index(value)
    if isinstance(value, str):
        key = value.strip()
        if not key:
            raise ValueError(f'{what}=""; expected {_HITBOX_FROM_EXPECT}.')
        low = key.lower()
        if low in _HITBOX_FROM_SPECIAL:
            return low
        if key in sheet._cycles:
            return key
        try:
            return sheet.frame_index(key)
        except (TypeError, ValueError):
            raise _hitbox_from_unknown(sheet, value, what) from None
    if isinstance(value, (tuple, list)):
        if len(value) == 0:
            raise ValueError(
                f"{what}=() is empty; expected one or more clip names."
            )
        names: List[str] = []
        for item in value:
            item = as_payload(item)
            if isinstance(item, bool) or not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"{what} tuple expected clip names, got {item!r}."
                )
            key = item.strip()
            if key not in sheet._cycles:
                raise _hitbox_from_unknown(sheet, value, what)
            names.append(key)
        return tuple(names)
    raise TypeError(
        f"{what} expected {_HITBOX_FROM_EXPECT}; got {type(value).__name__}."
    )


def _parse_hitbox_scale(value, what: str = "hitbox_scale") -> Tuple[float, float]:
    """Scalar or ``(sx, sy)``; both components ``>= 0`` (0 collapses that axis). Returns a pair."""
    value = as_payload(value)
    if value is None:
        raise TypeError(
            f"{what} expected a number >= 0 or a (sx, sy) pair; got None."
        )
    if isinstance(value, bool):
        raise TypeError(
            f"{what} expected a number >= 0 or a (sx, sy) pair; got bool."
        )
    if isinstance(value, (int, float)):
        s = _positive_number(value, what=what, exclusive=False)
        return (s, s)
    if isinstance(value, (tuple, list)):
        if len(value) != 2:
            raise TypeError(
                f"{what} expected a number >= 0 or a (sx, sy) pair; "
                f"got a {len(value)}-tuple."
            )
        sx = as_payload(value[0])
        sy = as_payload(value[1])
        if isinstance(sx, bool) or isinstance(sy, bool):
            raise TypeError(
                f"{what} expected a number >= 0 or a (sx, sy) pair; got bool."
            )
        return (
            _positive_number(sx, what=what, exclusive=False),
            _positive_number(sy, what=what, exclusive=False),
        )
    raise TypeError(
        f"{what} expected a number >= 0 or a (sx, sy) pair; "
        f"got {type(value).__name__}."
    )


def _parse_hitbox_anchor(value, what: str = "hitbox_anchor"):
    """String preset, or ``(ax, ay)`` in y-up local (not clamped to [-1, 1]).

    Preset writes round-trip as the string. Numeric writes round-trip as a pair.
    """
    value = as_payload(value)
    if value is None:
        return "center"
    if isinstance(value, str):
        key = value.strip().lower()
        if key in _HITBOX_ANCHORS:
            return key
        raise ValueError(
            f"{what}={value!r}; expected one of "
            f'{", ".join(repr(c) for c in _HITBOX_ANCHORS)}, '
            "or an (ax, ay) pair."
        )
    if isinstance(value, (tuple, list)) and not isinstance(value, bool):
        if len(value) != 2:
            raise TypeError(
                f"{what} expected an (ax, ay) pair or one of "
                f'{", ".join(repr(c) for c in _HITBOX_ANCHORS)}; '
                f"got a {len(value)}-tuple."
            )
        ax = as_payload(value[0])
        ay = as_payload(value[1])
        if (
            isinstance(ax, bool) or isinstance(ay, bool)
            or not isinstance(ax, (int, float))
            or not isinstance(ay, (int, float))
        ):
            raise TypeError(
                f"{what} (ax, ay) expected two numbers; "
                f"got {(type(ax).__name__, type(ay).__name__)}."
            )
        axf = float(ax)
        ayf = float(ay)
        if not math.isfinite(axf) or not math.isfinite(ayf):
            raise ValueError(
                f"{what} (ax, ay) expected finite numbers; "
                f"got {(axf, ayf)}."
            )
        return (axf, ayf)
    raise TypeError(
        f"{what} expected one of "
        f'{", ".join(repr(c) for c in _HITBOX_ANCHORS)} '
        f"or an (ax, ay) pair; got {type(value).__name__}."
    )


def _parse_clip_offset(value) -> Optional[Tuple[float, float]]:
    """``clip(offset=(dx, dy))``: art pixels, y-up. ``None`` = no offset."""
    value = as_payload(value)
    if value is None:
        return None
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise TypeError(
            "clip offset= expected a (dx, dy) pair in art pixels (y-up); "
            f"got {value!r}. Write sheet.clip(\"dead\", frames, offset=(12, 0))."
        )
    dx, dy = as_payload(value[0]), as_payload(value[1])
    for part in (dx, dy):
        if isinstance(part, bool) or not isinstance(part, (int, float)):
            raise TypeError(f"clip offset= expected two numbers; got {value!r}.")
    dxf, dyf = float(dx), float(dy)
    if not (math.isfinite(dxf) and math.isfinite(dyf)):
        raise ValueError(f"clip offset= expected finite numbers; got {value!r}.")
    return (dxf, dyf)


def _anchor_pair(anchor) -> Tuple[float, float]:
    if isinstance(anchor, str):
        return _HITBOX_ANCHOR_XY[anchor]
    return (float(anchor[0]), float(anchor[1]))


def _anchor_on_aabb(
    minx: float, miny: float, maxx: float, maxy: float, anchor,
) -> Tuple[float, float]:
    """Point on (or beyond) the AABB. ``anchor`` is a preset or ``(ax, ay)``."""
    ax, ay = _anchor_pair(anchor)
    cx = 0.5 * (minx + maxx)
    cy = 0.5 * (miny + maxy)
    hx = 0.5 * (maxx - minx)
    hy = 0.5 * (maxy - miny)
    return (cx + ax * hx, cy + ay * hy)


def _scale_about(
    px: float, py: float, ax: float, ay: float, sx: float, sy: float,
) -> Tuple[float, float]:
    return ax + (px - ax) * sx, ay + (py - ay) * sy


def _affine_ellipse(
    nx: float, ny: float, nrx: float, nry: float, ang: float,
    ax: float, ay: float, sx: float, sy: float,
    aw: float = 1.0, ah: float = 1.0,
) -> Tuple[float, float, float, float, float]:
    """Scale a local ellipse about ``(ax, ay)``. Returns ``(cx, cy, rx, ry, ang)``.

    Local ``nrx`` is a fraction of width, ``nry`` of height. Emit multiplies
    them by pose ``w`` / ``h`` separately, so this must not treat those
    components as Euclidean. Axis-aligned ellipses scale each radius on its
    own axis (SVD would sort singular values and swap onto 90°, after which
    emit applies the wrong dimension). Rotated ellipses SVD in equal units
    using the reference-cell aspect ``(aw, ah)``, then convert back.
    """
    cx, cy = _scale_about(nx, ny, ax, ay, sx, sy)
    rx = abs(float(nrx))
    ry = abs(float(nry))
    ang = float(ang)
    # θ ≈ k·π/2: non-uniform scale stays aligned with the stored axes.
    if abs(math.sin(2.0 * ang)) < 1e-12:
        c = math.cos(ang)
        sn = math.sin(ang)
        if abs(sn) < abs(c):
            return cx, cy, max(rx * sx, 1e-12), max(ry * sy, 1e-12), ang
        return cx, cy, max(rx * sy, 1e-12), max(ry * sx, 1e-12), ang
    aw = max(abs(float(aw)), 1e-12)
    ah = max(abs(float(ah)), 1e-12)
    c = math.cos(ang)
    sn = math.sin(ang)
    m00 = sx * c * rx * aw
    m01 = sx * (-sn) * ry * ah
    m10 = sy * sn * rx * aw
    m11 = sy * c * ry * ah
    u, sig, _vt = np.linalg.svd([[m00, m01], [m10, m11]])
    nrx2 = max(abs(float(sig[0])) / aw, 1e-12)
    nry2 = max(abs(float(sig[1])) / ah, 1e-12)
    if float(np.linalg.det(u)) < 0.0:
        u = np.array(u, copy=True)
        u[:, 1] *= -1.0
    nang = math.atan2(float(u[1, 0]), float(u[0, 0]))
    return cx, cy, nrx2, nry2, nang


def _parse_shield_scale(value) -> float:
    value = as_payload(value)
    if value is None:
        return _SPRITE_SHIELD_SCALE
    return _positive_number(value, what="shield_scale", exclusive=False)


def _parse_clip_name(name) -> str:
    """Non-empty clip name for the ``fps=`` shortcut (default ``\"default\"``)."""
    name = as_payload(name)
    if name is None:
        return _DEFAULT_CLIP_NAME
    if not isinstance(name, str) or not name:
        raise TypeError(
            'name= expected a non-empty clip name string. '
            'Write Sheet("run.png", cols=8, fps=8, name="walk").'
        )
    return name


def _parse_offset(offset) -> Tuple[float, float]:
    offset = as_payload(offset)
    if offset is None:
        return (0.0, 0.0)
    if isinstance(offset, (tuple, list)) and len(offset) == 2:
        from .validate import number
        return (number(as_payload(offset[0]), "offset dx"),
                number(as_payload(offset[1]), "offset dy"))
    raise TypeError(
        "offset expected (dx, dy) in design units, "
        f"got {type(offset).__name__}"
    )


def _flipped_art_angle(
    art_angle: float,
    *,
    flip_x: bool,
    flip_y: bool,
) -> float:
    """``art_angle`` after horizontal / vertical mirror (degrees)."""
    a = float(art_angle)
    if flip_x:
        a = 180.0 - a
    if flip_y:
        a = -a
    return a


def _rest_heading_from_pose(
    art_angle: float,
    *,
    flip_x: bool,
    flip_y: bool,
) -> float:
    """Construct-time / property rest heading for a sprite pose."""
    return _flipped_art_angle(art_angle, flip_x=flip_x, flip_y=flip_y)


def _parse_art_angle(value) -> float:
    """Bitmap nose in degrees (0 = +x, 90 = +y). Finite number; default 0."""
    value = as_payload(value)
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            "art_angle expected a number of degrees (0 = +x, 90 = +y), "
            f"got {type(value).__name__}. "
            'Write Sprite("ship.png", art_angle=90).'
        )
    from .validate import number
    return number(value, "art_angle")


def _fit_size(
    px_w: int,
    px_h: int,
    *,
    width: Optional[float],
    height: Optional[float],
    size: Optional[float],
) -> Tuple[float, float]:
    """Design-unit (w, h) from pixel aspect and the size kwargs."""
    aspect = (px_w / px_h) if px_h > 0 else 1.0
    n_set = sum(v is not None for v in (width, height, size))
    if size is not None and (width is not None or height is not None):
        raise TypeError(
            "use size= (longer side) or width= / height=, not size= together with "
            "width= or height=. size= keeps aspect; width= and height= together stretch."
        )
    for label, value in (("width", width), ("height", height), ("size", size)):
        if callable(value) and not isinstance(value, type):
            raise TypeError(
                f"Sprite {label}= is fixed (play / frame= re-fit the body). "
                "Link the scale instead: sprite['scale'] @= lambda: …"
            )
    if width is not None:
        width = _positive_number(width, what="width", exclusive=False)
    if height is not None:
        height = _positive_number(height, what="height", exclusive=False)
    if size is not None:
        size = _positive_number(size, what="size", exclusive=False)
        if aspect >= 1.0:
            return size, size / aspect
        return size * aspect, size
    if width is not None and height is not None:
        return width, height
    if width is not None:
        return width, width / aspect
    if height is not None:
        return height * aspect, height
    longer = _default_size()
    if aspect >= 1.0:
        return longer, longer / aspect
    return longer * aspect, longer


def _parse_size_intent(
    width: Optional[float],
    height: Optional[float],
    size: Optional[float],
) -> Tuple[str, Optional[float]]:
    """Which construct kwarg to keep when ``play`` / ``frame=`` retargets aspect."""
    if size is not None:
        return "size", float(size)
    if width is not None and height is not None:
        return "both", None
    if width is not None:
        return "width", None
    if height is not None:
        return "height", None
    return "default", None


def _svg_warn_once(kind: str, text: str, message: str) -> None:
    key = (kind, text if len(text) <= 160 else text[:160])
    if key in _SVG_WARNED:
        return
    _SVG_WARNED.add(key)
    warnings.warn(message, RuntimeWarning, skip_file_prefixes=_WARN_SKIP)


def _svg_looks_like_markup(text: str) -> bool:
    return "<" in text


def _svg_attr_pair(markup: str) -> Optional[Tuple[float, float]]:
    """Root ``width`` / ``height`` numbers, ignoring ``stroke-width`` and kin.

    A hyphenated name ends in ``width``; ``\\b`` still matches there. Require a
    non-hyphen (start or whitespace) immediately before the attribute. A
    malformed number falls through so the raster can use the next size source.
    """
    wm = re.search(
        r'<svg\b[^>]*[^\w-]width\s*=\s*["\']?\s*([-\d.eE+]+)',
        markup,
        flags=re.IGNORECASE,
    )
    hm = re.search(
        r'<svg\b[^>]*[^\w-]height\s*=\s*["\']?\s*([-\d.eE+]+)',
        markup,
        flags=re.IGNORECASE,
    )
    if wm is None or hm is None:
        return None
    try:
        w, h = float(wm.group(1)), float(hm.group(1))
    except (TypeError, ValueError):
        return None
    if w > 0.0 and h > 0.0 and math.isfinite(w) and math.isfinite(h):
        return w, h
    return None


def _svg_intrinsic_wh(markup: str) -> Tuple[float, float]:
    """Best-effort width/height from viewBox or root width/height attrs."""
    m = _VIEWBOX_RE.search(markup)
    if m is not None:
        try:
            w, h = float(m.group(3)), float(m.group(4))
        except (TypeError, ValueError):
            w = h = 0.0
        if w > 0.0 and h > 0.0 and math.isfinite(w) and math.isfinite(h):
            return w, h
    pair = _svg_attr_pair(markup)
    if pair is not None:
        return pair
    return float(_SVG_MIN_PX), float(_SVG_MIN_PX)


def _svg_pixel_ratio() -> float:
    try:
        from .canvas import ScenaCanvas
        canvas = ScenaCanvas.get_current()
        pr = float(getattr(canvas, "pixel_ratio", 1.0) or 1.0)
        return pr if pr > 0.0 else 1.0
    except Exception:
        return 1.0


def _raster_svg(
    markup: str,
    *,
    dest_longer: Optional[float] = None,
) -> Tuple[skia.Image, bool]:
    """Rasterize SVG markup to a Skia image. Returns ``(image, ok)``."""
    try:
        data = skia.Data.MakeWithCopy(markup.encode("utf-8"))
        stream = skia.MemoryStream.Make(data)
        dom = skia.SVGDOM.MakeFromStream(stream)
        if dom is None:
            raise ValueError("SVGDOM.MakeFromStream returned None")
        iw, ih = _svg_intrinsic_wh(markup)
        cs = dom.containerSize()
        cw, ch = float(cs.width()), float(cs.height())
        if cw <= 0.0 or ch <= 0.0 or not math.isfinite(cw) or not math.isfinite(ch):
            cw, ch = iw, ih
            dom.setContainerSize(skia.Size(cw, ch))
        aspect = (cw / ch) if ch > 0.0 else 1.0
        longer = float(dest_longer) if dest_longer is not None else float(_SVG_MIN_PX)
        if not math.isfinite(longer) or longer <= 0.0:
            longer = float(_SVG_MIN_PX)
        longer = max(float(_SVG_MIN_PX), longer * _svg_pixel_ratio())
        if aspect >= 1.0:
            px_w = int(round(longer))
            px_h = max(1, int(round(longer / aspect)))
        else:
            px_h = int(round(longer))
            px_w = max(1, int(round(longer * aspect)))
        px_w = max(1, px_w)
        px_h = max(1, px_h)
        info = skia.ImageInfo.Make(
            px_w, px_h, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType,
        )
        surf = skia.Surface.MakeRaster(info)
        if surf is None:
            raise ValueError("failed to create raster surface")
        canvas = surf.getCanvas()
        canvas.clear(skia.ColorTRANSPARENT)
        canvas.save()
        canvas.scale(px_w / cw, px_h / ch)
        dom.render(canvas)
        canvas.restore()
        img = surf.makeImageSnapshot()
        if img is None:
            raise ValueError("makeImageSnapshot returned None")
        return img, True
    except Exception as e:
        _svg_warn_once(
            "parse",
            markup,
            f"Svg failed to parse markup ({e}). Using a placeholder. "
            "The actor is still valid.",
        )
        return _make_placeholder("svg"), False


def _sheet_from_image(img: skia.Image, *, placeholder: bool, display: str = "svg") -> Sheet:
    """Private single-frame Sheet from a raster (not interned)."""
    sheet = Sheet.__new__(Sheet)
    from .atlas import alloc_sheet_token, release_sheet_token
    import weakref
    sheet._cache_token = alloc_sheet_token()
    weakref.finalize(sheet, release_sheet_token, sheet._cache_token)
    sheet._source = ""
    sheet._placeholder = bool(placeholder)
    sheet._display = display
    sheet._cols_arg = None
    sheet._rows_arg = None
    sheet._cell = None
    sheet._cycles = {}
    sheet._selector_cache = None
    sheet._packed = False
    sheet._is_atlas = False
    sheet._missing_atlas = False
    sheet._shared = False
    sheet._interned = False
    sheet._name_to_index = {}
    sheet._names = ()
    sheet._px_w = max(1, int(img.width()))
    sheet._px_h = max(1, int(img.height()))
    sheet._cell_w, sheet._cell_h, sheet._cols, sheet._rows, sheet._nframes = _sheet_layout(
        sheet._px_w, sheet._px_h, cols=None, rows=None, cell=None,
    )
    sheet._src = tuple(
        _cell_src(sheet._cell_w, sheet._cell_h, sheet._cols, i)
        for i in range(sheet._nframes)
    )
    sheet._atlas_frames = tuple(
        _grid_frame(i, sheet._cell_w, sheet._cell_h, sheet._cols)
        for i in range(sheet._nframes)
    )
    sheet._set_single_image_backing(img)
    sheet._apply_frame_names()
    seal(sheet)   # built without __init__: close it here
    return sheet


def _labeled_placeholder_sheet(label: str) -> Sheet:
    """Interned one-cell checker labeled with the missing frame / file name."""
    key = ("placeholder", label)
    hit = _intern_get(key)
    if hit is not None:
        return hit
    img = _make_placeholder(label)
    sheet = _sheet_from_image(img, placeholder=True, display=label)
    sheet._source = label
    return _intern_put(key, sheet)


def _warn_unknown_frame(sheet: Sheet, key: str) -> None:
    ident = getattr(sheet, "_source", None) or getattr(sheet, "_display", "") or id(sheet)
    warn_key = f"frame:{ident}:{key}"
    if warn_key in _MISSING_WARNED:
        return
    _MISSING_WARNED.add(warn_key)
    warnings.warn(
        f"{sheet._unknown_frame_message(key)} Using a placeholder. "
        "The actor is still valid.",
        RuntimeWarning,
        skip_file_prefixes=_WARN_SKIP,
    )


# ---------------------------------------------------------------------------
# Sprite
# ---------------------------------------------------------------------------

def _emit_baked_specs(
    bake, flip_host, pcx: float, pcy: float, ang: float, w: float, h: float,
) -> List[Tuple]:
    """World prims for baked ``_hitbox_*`` locals under one rigid placement.

    ``bake`` holds the locals (Sprite body or ``Hitbox`` part). ``flip_host``
    is the Sprite whose ``flip_*`` reflect them. A local ``(nx, ny)`` lands at
    ``(pcx, pcy) + R(ang) · flip(nx·w, ny·h)``; ``(pcx, pcy)`` already holds
    the flipped offset. Empty locals → ``[]``.
    """
    c = math.cos(ang)
    sn = math.sin(ang)
    out: List[Tuple] = []
    circle_locals = bake._hitbox_circles
    if not circle_locals and bake._hitbox_circle is not None:
        circle_locals = (bake._hitbox_circle,)
    if circle_locals:
        aw = float(bake._hitbox_ref_src_w) or 1.0
        ah = float(bake._hitbox_ref_src_h) or 1.0
        src_aspect = aw / ah
        for nx, ny, nr in circle_locals:
            nx, ny = flip_host._apply_local_flip(float(nx), float(ny))
            lx = nx * w
            ly = ny * h
            bx = pcx + lx * c - ly * sn
            by = pcy + lx * sn + ly * c
            # ``nr`` is radius / source width. A stretched design box
            # (``w/h != src_w/src_h``) makes that a world ellipse.
            # Near-square stays a circle (``ellipse_as_circle``, 1.08).
            rx = abs(float(nr)) * w
            ry = abs(float(nr)) * h * src_aspect
            r_circ = ellipse_as_circle(rx, ry)
            if r_circ is None and max(rx, ry) <= 1e-12:
                r_circ = rx
            if r_circ is not None:
                out.append(("circle", bx, by, r_circ))
            else:
                total_ang = ang + flip_host._flip_local_angle(0.0)
                out.append(("ellipse", bx, by, rx, ry, total_ang))
    ellipse_locals = bake._hitbox_ellipses
    if not ellipse_locals and bake._hitbox_ellipse is not None:
        ellipse_locals = (bake._hitbox_ellipse,)
    for nx, ny, nrx, nry, local_ang in ellipse_locals:
        nx, ny = flip_host._apply_local_flip(float(nx), float(ny))
        lx = nx * w
        ly = ny * h
        bx = pcx + lx * c - ly * sn
        by = pcy + lx * sn + ly * c
        rx = abs(float(nrx)) * w
        ry = abs(float(nry)) * h
        r_circ = ellipse_as_circle(rx, ry)
        if r_circ is not None:
            out.append(("circle", bx, by, r_circ))
        else:
            total_ang = ang + flip_host._flip_local_angle(float(local_ang))
            out.append(("ellipse", bx, by, rx, ry, total_ang))
    if bake._hitbox_poly:
        out_poly: List[Tuple[float, float]] = []
        for nx, ny in bake._hitbox_poly:
            nx, ny = flip_host._apply_local_flip(float(nx), float(ny))
            lx = nx * w
            ly = ny * h
            wx = pcx + lx * c - ly * sn
            wy = pcy + lx * sn + ly * c
            out_poly.append((wx, wy))
        if len(out_poly) >= 3:
            out.append(("poly", tuple(out_poly)))
    for nx, ny, nw, nh in bake._hitbox_boxes:
        nx, ny = flip_host._apply_local_flip(float(nx), float(ny))
        bw = abs(float(nw)) * w
        bh = abs(float(nh)) * h
        lx = nx * w
        ly = ny * h
        bx = pcx + lx * c - ly * sn
        by = pcy + lx * sn + ly * c
        hw, hh = bw * 0.5, bh * 0.5
        if abs(ang) < 1e-6 or abs(abs(ang) - math.pi) < 1e-6:
            out.append(("aabb", bx - hw, by - hh, bx + hw, by + hh))
        else:
            out.append(("obb", bx, by, hw, hh, ang))
    return out


class _HitboxBakeMixin:
    """Hitbox bake shared by the Sprite body and its hitbox parts.

    The methods keep their Sprite spelling. A host class supplies the bake
    state slots (``_hitbox_*``, ``_auto_baked``, ``_collision_epoch``) and
    the read-only host protocol the bake reads: ``_sheet``, ``_play_frames``,
    ``_play_name``, ``_frame``, ``_construct_frame``, ``_current_frame_index()``,
    ``_size_intent``, ``_size_intent_value``, ``_scale``, ``_du_per_px()``,
    ``_collidable``. ``Sprite`` is its own host; ``Hitbox`` forwards them.
    """

    __slots__ = ()

    def _clear_auto_hitbox(self) -> None:
        self._hitbox_boxes = ()
        self._hitbox_circle = None
        self._hitbox_circles = ()
        self._hitbox_ellipse = None
        self._hitbox_ellipses = ()
        self._hitbox_poly = ()
        self._hitbox_base_boxes = ()
        self._hitbox_base_circle = None
        self._hitbox_base_circles = ()
        self._hitbox_base_ellipse = None
        self._hitbox_base_ellipses = ()
        self._hitbox_base_poly = ()
        self._hitbox_local_radius = 0.0
        self._hitbox_extent_x = 0.0
        self._hitbox_extent_y = 0.0
        self._hitbox_extent_pose = None

    def _snapshot_hitbox_base(self) -> None:
        self._hitbox_base_boxes = self._hitbox_boxes
        self._hitbox_base_circle = self._hitbox_circle
        self._hitbox_base_circles = self._hitbox_circles
        self._hitbox_base_ellipse = self._hitbox_ellipse
        self._hitbox_base_ellipses = self._hitbox_ellipses
        self._hitbox_base_poly = self._hitbox_poly

    def _restore_hitbox_base(self) -> None:
        self._hitbox_boxes = self._hitbox_base_boxes
        self._hitbox_circle = self._hitbox_base_circle
        self._hitbox_circles = self._hitbox_base_circles
        self._hitbox_ellipse = self._hitbox_base_ellipse
        self._hitbox_ellipses = self._hitbox_base_ellipses
        self._hitbox_poly = self._hitbox_base_poly

    def _local_prims_aabb(self) -> Optional[Tuple[float, float, float, float]]:
        minx = miny = 1e300
        maxx = maxy = -1e300
        found = False
        # ``nrx`` / ``nr`` are fractions of width, ``nry`` of height. Extents
        # must stay in those units: emit multiplies x by pose width and y by
        # pose height. A rotated ellipse (or a circle) on a non-square cell
        # is not Euclidean in this space — same split as ``_affine_ellipse``.
        # Circles keep the reference-cell aspect (``nr`` is a width fraction).
        # Rotated ellipses use the pose aspect: emit scales ``nrx`` by pose
        # width and ``nry`` by pose height, so a stretched design box is not
        # the source-pixel aspect.
        aw = float(self._hitbox_ref_src_w) or 1.0
        ah = float(self._hitbox_ref_src_h) or 1.0
        aspect = aw / ah
        pw, ph = self._hitbox_pose_wh()
        pw, ph = abs(float(pw)), abs(float(ph))
        if pw >= 1e-12 and ph >= 1e-12:
            pose_aspect = pw / ph
            pose_inv = ph / pw
        else:
            pose_aspect = aspect
            pose_inv = ah / aw
        circles = self._hitbox_circles
        if not circles and self._hitbox_circle is not None:
            circles = (self._hitbox_circle,)
        for nx, ny, nr in circles:
            rx = abs(float(nr))
            ry = rx * aspect
            minx = min(minx, float(nx) - rx)
            maxx = max(maxx, float(nx) + rx)
            miny = min(miny, float(ny) - ry)
            maxy = max(maxy, float(ny) + ry)
            found = True
        ellipses = self._hitbox_ellipses
        if not ellipses and self._hitbox_ellipse is not None:
            ellipses = (self._hitbox_ellipse,)
        for nx, ny, nrx, nry, ang in ellipses:
            c = math.cos(float(ang))
            sn = math.sin(float(ang))
            rx, ry = abs(float(nrx)), abs(float(nry))
            ex = math.sqrt(_sq(rx * c) + _sq(ry * pose_inv * sn))
            ey = math.sqrt(_sq(rx * pose_aspect * sn) + _sq(ry * c))
            minx = min(minx, float(nx) - ex)
            maxx = max(maxx, float(nx) + ex)
            miny = min(miny, float(ny) - ey)
            maxy = max(maxy, float(ny) + ey)
            found = True
        for nx, ny in self._hitbox_poly:
            minx = min(minx, float(nx))
            maxx = max(maxx, float(nx))
            miny = min(miny, float(ny))
            maxy = max(maxy, float(ny))
            found = True
        for nx, ny, nw, nh in self._hitbox_boxes:
            hw, hh = abs(float(nw)) * 0.5, abs(float(nh)) * 0.5
            minx = min(minx, float(nx) - hw)
            maxx = max(maxx, float(nx) + hw)
            miny = min(miny, float(ny) - hh)
            maxy = max(maxy, float(ny) + hh)
            found = True
        if not found:
            return None
        return (minx, miny, maxx, maxy)

    def _translate_hitbox_locals(self, dx: float, dy: float) -> None:
        if abs(dx) < 1e-15 and abs(dy) < 1e-15:
            return
        circles = self._hitbox_circles
        if not circles and self._hitbox_circle is not None:
            circles = (self._hitbox_circle,)
        if circles:
            moved = tuple((nx + dx, ny + dy, nr) for nx, ny, nr in circles)
            self._hitbox_circles = moved
            self._hitbox_circle = moved[0] if len(moved) == 1 else None
        ellipses = self._hitbox_ellipses
        if not ellipses and self._hitbox_ellipse is not None:
            ellipses = (self._hitbox_ellipse,)
        if ellipses:
            moved_e = tuple(
                (nx + dx, ny + dy, nrx, nry, ang)
                for nx, ny, nrx, nry, ang in ellipses
            )
            self._hitbox_ellipses = moved_e
            self._hitbox_ellipse = moved_e[0] if len(moved_e) == 1 else None
        if self._hitbox_poly:
            self._hitbox_poly = tuple((x + dx, y + dy) for x, y in self._hitbox_poly)
        if self._hitbox_boxes:
            self._hitbox_boxes = tuple(
                (nx + dx, ny + dy, nw, nh) for nx, ny, nw, nh in self._hitbox_boxes
            )

    def _bake_reference_local_aabb(self) -> Optional[Tuple[float, float, float, float]]:
        """Alpha AABB of this bake's frames, in the same local space as the prims.

        The pin target is ``hitbox_from`` (construct frame, clip, ``"each"``,
        ``"all"``, or a clip tuple) — not every cell in the sheet. When the
        reference frame has authored boxes, those boxes are the target (the
        same shortcut the shape bake uses); otherwise the mask bbox.
        """
        indices = self._hitbox_indices_or_construct()
        if not indices:
            return None
        sheet = self._sheet
        ref_idx = int(indices[0])
        if int(self._hitbox_frame) in {int(i) for i in indices}:
            ref_idx = int(self._hitbox_frame)
        try:
            ref = sheet._frame_at(ref_idx)
        except (ValueError, IndexError, KeyError):
            return None
        if ref.boxes:
            locals_b = boxes_to_local(ref.boxes, ref)
        else:
            order = (ref_idx,) + tuple(int(i) for i in indices if int(i) != ref_idx)
            try:
                items = tuple(
                    (sheet._image_for_frame(int(i)), sheet._frame_at(int(i)))
                    for i in order
                )
                col = auto_collider_for_frames(
                    items, force_kind="bbox", scales=self._hitbox_union_scales(order),
                )
            except (ValueError, IndexError, KeyError):
                return None
            if not col or not col.boxes:
                return None
            locals_b = boxes_to_local(col.boxes, ref)
        minx = miny = 1e300
        maxx = maxy = -1e300
        for nx, ny, nw, nh in locals_b:
            hw, hh = abs(float(nw)) * 0.5, abs(float(nh)) * 0.5
            minx = min(minx, float(nx) - hw)
            maxx = max(maxx, float(nx) + hw)
            miny = min(miny, float(ny) - hh)
            maxy = max(maxy, float(ny) + hh)
        if maxx < minx:
            return None
        return (minx, miny, maxx, maxy)

    def _pin_hitbox_anchor(self) -> None:
        ax, ay = _anchor_pair(self._hitbox_anchor)
        if abs(ax) < 1e-15 and abs(ay) < 1e-15:
            return
        shape = self._local_prims_aabb()
        union = self._bake_reference_local_aabb()
        if shape is None or union is None:
            return
        sa = _anchor_on_aabb(*shape, self._hitbox_anchor)
        ua = _anchor_on_aabb(*union, self._hitbox_anchor)
        self._translate_hitbox_locals(ua[0] - sa[0], ua[1] - sa[1])

    def _apply_hitbox_shaping(self) -> None:
        """Fold ``hitbox_scale`` / ``hitbox_anchor`` into the emitted locals."""
        self._restore_hitbox_base()
        self._pin_hitbox_anchor()
        aabb = self._local_prims_aabb()
        if aabb is None:
            self._recompute_hitbox_local_radius()
            return
        ax, ay = _anchor_on_aabb(*aabb, self._hitbox_anchor)
        sx, sy = self._hitbox_scale
        if abs(sx - 1.0) < 1e-15 and abs(sy - 1.0) < 1e-15:
            self._recompute_hitbox_local_radius()
            return
        circles = self._hitbox_circles
        if not circles and self._hitbox_circle is not None:
            circles = (self._hitbox_circle,)
        ellipses = self._hitbox_ellipses
        if not ellipses and self._hitbox_ellipse is not None:
            ellipses = (self._hitbox_ellipse,)
        # Shape each family on its own. A non-uniform circle scale becomes
        # ellipses; those must be concatenated with ellipses already baked,
        # never written over them. Uniform scale must still reach ellipses
        # when circles are also present.
        new_c: Tuple = ()
        new_e_conv: Tuple = ()
        new_e_orig: Tuple = ()
        if circles:
            if abs(sx - sy) < 1e-12:
                new_c = tuple(
                    (*_scale_about(nx, ny, ax, ay, sx, sy), abs(nr) * sx)
                    for nx, ny, nr in circles
                )
            else:
                aw = float(self._hitbox_ref_src_w) or 1.0
                ah = float(self._hitbox_ref_src_h) or 1.0
                aspect = aw / ah
                # ``nr`` is a fraction of width. Emit multiplies ``nry`` by
                # pose height alone, so the source aspect has to live in
                # ``nry`` or a 64×128 cell doubles ``ry``.
                new_e_conv = tuple(
                    (
                        *_scale_about(nx, ny, ax, ay, sx, sy),
                        abs(nr) * sx,
                        abs(nr) * sy * aspect,
                        0.0,
                    )
                    for nx, ny, nr in circles
                )
        if ellipses:
            aw = float(self._hitbox_ref_src_w) or 1.0
            ah = float(self._hitbox_ref_src_h) or 1.0
            new_e_orig = tuple(
                _affine_ellipse(nx, ny, nrx, nry, eang, ax, ay, sx, sy, aw, ah)
                for nx, ny, nrx, nry, eang in ellipses
            )
        if circles or ellipses:
            merged_e = new_e_conv + new_e_orig
            self._hitbox_circles = new_c
            self._hitbox_circle = new_c[0] if len(new_c) == 1 else None
            self._hitbox_ellipses = merged_e
            self._hitbox_ellipse = merged_e[0] if len(merged_e) == 1 else None
        if self._hitbox_poly:
            self._hitbox_poly = tuple(
                _scale_about(x, y, ax, ay, sx, sy) for x, y in self._hitbox_poly
            )
        if self._hitbox_boxes:
            self._hitbox_boxes = tuple(
                (
                    *_scale_about(nx, ny, ax, ay, sx, sy),
                    abs(nw) * sx,
                    abs(nh) * sy,
                )
                for nx, ny, nw, nh in self._hitbox_boxes
            )
        self._recompute_hitbox_local_radius()

    def _commit_hitbox_base(self) -> None:
        self._snapshot_hitbox_base()
        self._apply_hitbox_shaping()
        self._auto_baked = True

    def _recompute_hitbox_local_radius(self, pose_wh=None) -> None:
        """Separate x/y extents for the broad-phase proxy.

        A circle's ``nr`` is a fraction of width; its height fraction is
        ``nr * src_w / src_h``. The proxy is the AABB of the box
        ``(ex * w, ey * h)`` turned by the heading, so each extent must hold
        what ``_collision_specs`` emits *and* that prim's own AABB:

        - a near-square pair that emits as a circle uses the mean radius
          (``ellipse_as_circle``), which is wider than the smaller axis;
        - an ellipse carries the AABB of its turned box, not its tight one.

        Both depend on the pose aspect, so the extents remember the pose they
        were built for (``_hitbox_extent_pose``) and the proxy rebuilds them
        when the pose box changes. One scalar times ``hypot(w, h)`` drops a
        wide source drawn into a square. ``_hitbox_local_radius`` keeps
        ``hypot(ex, ey)``.
        """
        ex = 0.0
        ey = 0.0
        aw = float(self._hitbox_ref_src_w) or 1.0
        ah = float(self._hitbox_ref_src_h) or 1.0
        src_aspect = aw / ah
        if pose_wh is None:
            pose_wh = self._hitbox_pose_wh()
        pw, ph = abs(float(pose_wh[0])), abs(float(pose_wh[1]))
        live_pose = pw >= 1e-12 and ph >= 1e-12
        if live_pose:
            pose_aspect = pw / ph
            pose_inv = ph / pw
        else:
            pose_aspect = src_aspect
            pose_inv = ah / aw
        circles = self._hitbox_circles
        if not circles and self._hitbox_circle is not None:
            circles = (self._hitbox_circle,)
        for nx, ny, nr in circles:
            rx = abs(float(nr))
            ry = rx * src_aspect
            if live_pose:
                r_circ = ellipse_as_circle(rx * pw, ry * ph)
                if r_circ is not None:
                    rx, ry = r_circ / pw, r_circ / ph
            ex = max(ex, abs(float(nx)) + rx)
            ey = max(ey, abs(float(ny)) + ry)
        ellipses = self._hitbox_ellipses
        if not ellipses and self._hitbox_ellipse is not None:
            ellipses = (self._hitbox_ellipse,)
        for nx, ny, nrx, nry, ang in ellipses:
            rx, ry = abs(float(nrx)), abs(float(nry))
            r_circ = ellipse_as_circle(rx * pw, ry * ph) if live_pose else None
            if r_circ is not None:
                hx, hy = r_circ / pw, r_circ / ph
            else:
                c = abs(math.cos(float(ang)))
                sn = abs(math.sin(float(ang)))
                hx = rx * c + ry * pose_inv * sn
                hy = rx * pose_aspect * sn + ry * c
            ex = max(ex, abs(float(nx)) + hx)
            ey = max(ey, abs(float(ny)) + hy)
        for nx, ny in self._hitbox_poly:
            ex = max(ex, abs(float(nx)))
            ey = max(ey, abs(float(ny)))
        for nx, ny, nw, nh in self._hitbox_boxes:
            ex = max(ex, abs(float(nx)) + abs(float(nw)) * 0.5)
            ey = max(ey, abs(float(ny)) + abs(float(nh)) * 0.5)
        self._hitbox_extent_x = ex
        self._hitbox_extent_y = ey
        self._hitbox_extent_pose = (pw, ph)
        self._hitbox_local_radius = math.hypot(ex, ey)

    def _hitbox_extents_for_pose(self, pw: float, ph: float) -> Tuple[float, float]:
        """``(ex, ey)`` built for pose box ``(pw, ph)``; rebuilt when it changed."""
        if self._hitbox_extent_pose != (pw, ph):
            self._recompute_hitbox_local_radius((pw, ph))
        return self._hitbox_extent_x, self._hitbox_extent_y

    def _invalidate_auto_bake(self) -> None:
        self._auto_baked = False
        self._hitbox_locked_kind = None
        self._hitbox_baked_key = None
        self._clear_auto_hitbox()
        from .entity import _bump_collision_epoch
        _bump_collision_epoch(self)

    def _clip_frame_list(self, name: str) -> Tuple[int, ...]:
        frames, _, _ = self._sheet._cycles[name]
        return tuple(int(i) for i in frames)

    def _union_clip_indices(self, names) -> Tuple[int, ...]:
        """Clip frames in registration order, first occurrence kept."""
        seen = set()
        out: List[int] = []
        for name in names:
            for i in self._clip_frame_list(name):
                if i not in seen:
                    seen.add(i)
                    out.append(i)
        return tuple(out)

    def _still_hitbox_index(self) -> int:
        sheet = self._sheet
        n = int(sheet._nframes)
        if n <= 0:
            return 0
        if self._play_frames:
            return int(self._current_frame_index()) % n
        return int(self._frame) % n

    def _construct_hitbox_index(self) -> int:
        sheet = self._sheet
        n = int(sheet._nframes)
        if n <= 0:
            return 0
        return int(self._construct_frame) % n

    def _clip_hitbox_key(self):
        """Identity of the ``hitbox_from="clip"`` reference set."""
        if self._play_name:
            return ("play", self._play_name)
        # Still (no clip playing) always bakes the construct frame. Keying on
        # the current ``frame`` invalidated an identical bake on every write.
        return ("still", int(self._construct_frame))

    def _hitbox_from_indices(self) -> Tuple[int, ...]:
        """Ordered frame indices that define the collider (empty if the sheet has none)."""
        spec = self._hitbox_from
        sheet = self._sheet
        n = int(sheet._nframes)
        if n <= 0:
            return ()
        if spec == "each":
            return (self._still_hitbox_index(),)
        if spec == "clip":
            if self._play_name and self._play_name in sheet._cycles:
                out = self._union_clip_indices((self._play_name,))
                return out if out else (self._construct_hitbox_index(),)
            return (self._construct_hitbox_index(),)
        if spec == "all":
            if sheet._cycles:
                out = self._union_clip_indices(sheet._cycles)
                return out if out else (self._construct_hitbox_index(),)
            return (self._construct_hitbox_index(),)
        if isinstance(spec, tuple):
            out = self._union_clip_indices(spec)
            return out if out else (self._construct_hitbox_index(),)
        if isinstance(spec, int):
            return (sheet.frame_index(spec),)
        if isinstance(spec, str) and spec in sheet._cycles:
            out = self._clip_frame_list(spec)
            return out if out else (0,)
        return (sheet.frame_index(spec),)

    def _hitbox_indices_or_construct(self) -> Tuple[int, ...]:
        """Reference-set indices, or the construct frame when the catalog is stale.

        ``hitbox_from`` is validated at set time. A later sheet edit (dropped
        clip, unknown name, empty sheet) must not raise out of ``step()``.
        """
        try:
            return self._hitbox_from_indices()
        except (ValueError, IndexError, KeyError):
            _warn_stale_hitbox_from(self)
            return (self._construct_hitbox_index(),)

    def _hitbox_force_kind(self) -> Optional[str]:
        return _HITBOX_FORCE_KIND.get(self._hitbox_kind)

    def _hitbox_display_anchor_index(self, frame_index: int) -> int:
        """Cell whose design box ``frame_index`` is stretched into when drawn.

        ``play()`` fits the first frame of a clip and stretches the rest into
        that box. ``"all"`` uses the first registered clip that contains the
        cell. A still, ``"each"``, or a lone index uses the cell itself.
        """
        spec = self._hitbox_from
        sheet = self._sheet
        idx = int(frame_index)
        if spec == "all":
            names = sheet._cycles
        elif spec == "clip":
            name = self._play_name
            names = (name,) if name and name in sheet._cycles else ()
        elif isinstance(spec, tuple):
            names = spec
        elif isinstance(spec, str) and spec in sheet._cycles:
            names = (spec,)
        else:
            return idx
        for name in names:
            if name not in sheet._cycles:
                continue
            frames = self._clip_frame_list(name)
            if idx in frames and frames:
                return int(frames[0])
        return idx

    def _hitbox_union_scales(
        self, indices: Sequence[int],
    ) -> Tuple[Tuple[float, float], ...]:
        """Blit placement of each bake frame, in the first index's source pixels.

        One design-units-per-pixel scale per sprite (``_du_per_px``): every
        cell's pixels land at the same size, so it is identity for each frame
        (a per-frame helper that always returned ``(1, 1)`` is gone; SA19)."""
        return ((1.0, 1.0),) * len(indices)

    def _apply_source_collider(self, col, fr) -> None:
        """Copy a source-space ``AutoCollider`` into local prims. Empty → design-box fallback."""
        if col is None or not col:
            self._auto_baked = True
            return
        src_circles = col.circles or ((col.circle,) if col.circle is not None else ())
        if col.kind in ("circle", "circles") and src_circles:
            locals_c = tuple(circle_to_local(*c, fr) for c in src_circles)
            self._hitbox_circles = locals_c
            self._hitbox_circle = locals_c[0] if len(locals_c) == 1 else None
            self._commit_hitbox_base()
            return
        src_ells = col.ellipses or ((col.ellipse,) if col.ellipse is not None else ())
        if col.kind in ("ellipse", "ellipses") and src_ells:
            locals_e = tuple(ellipse_to_local(*e, fr) for e in src_ells)
            self._hitbox_ellipses = locals_e
            self._hitbox_ellipse = locals_e[0] if len(locals_e) == 1 else None
            self._commit_hitbox_base()
            return
        if col.kind == "poly" and col.poly:
            self._hitbox_poly = hull_to_local(col.poly, fr)
            self._commit_hitbox_base()
            return
        if col.kind == "boxes" and col.boxes:
            self._hitbox_boxes = boxes_to_local(col.boxes, fr)
            self._commit_hitbox_base()
            return
        self._auto_baked = True

    def _ensure_auto_baked(self) -> None:
        """Bake the collider from the ``hitbox_from`` reference set (lazy on enroll)."""
        kind = self._hitbox_kind
        if kind not in _HITBOX_CHOICES:
            return
        spec = self._hitbox_from
        if spec == "each":
            idx = self._still_hitbox_index()
            if self._auto_baked and int(self._hitbox_frame) == int(idx):
                return
            indices = (int(idx),)
        elif spec == "clip":
            if self._play_frames:
                self._current_frame_index()
            key = self._clip_hitbox_key()
            if self._auto_baked and self._hitbox_baked_key == key:
                return
            if self._auto_baked:
                self._hitbox_locked_kind = None
                from .entity import _bump_collision_epoch
                _bump_collision_epoch(self)
            indices = self._hitbox_indices_or_construct()
        else:
            if self._auto_baked:
                return
            indices = self._hitbox_indices_or_construct()
            if not indices:
                indices = (int(self._construct_frame),)
        if not indices:
            indices = (self._construct_hitbox_index(),)
        try:
            self._bake_hitbox(spec, indices)
        finally:
            # A bake sets the hitbox reference size the pose key reads and the
            # prims the tilt pivot reads (the draw box): a pose input changed
            # with no other write (Collision Design, "Pose revision").
            bump_pose_rev(self)

    def _bake_hitbox(self, spec, indices) -> None:
        """``_ensure_auto_baked``'s bake of ``indices`` (the frames it reads)."""
        self._hitbox_frame = int(indices[0])
        self._clear_auto_hitbox()
        sheet = self._sheet
        try:
            ref = sheet._frame_at(int(indices[0]))
        except (ValueError, IndexError, KeyError):
            _warn_stale_hitbox_from(self)
            self._auto_baked = True
            return
        self._hitbox_ref_src_w = float(ref.src_w)
        self._hitbox_ref_src_h = float(ref.src_h)
        force = self._hitbox_force_kind()
        lockable = force is None and spec in ("each", "clip")
        if lockable and self._hitbox_locked_kind:
            force = self._hitbox_locked_kind
        # Locked ``"boxes"`` refit still prefers authored boxes. Explicit
        # circle / ellipse / hull / rect forces do not (author kind wins).
        if ref.boxes and (force is None or force == "boxes"):
            self._hitbox_boxes = boxes_to_local(ref.boxes, ref)
            if lockable:
                self._hitbox_locked_kind = "boxes"
            if spec == "clip":
                self._hitbox_baked_key = self._clip_hitbox_key()
            self._commit_hitbox_base()
            return
        items = tuple(
            (sheet._image_for_frame(int(i)), sheet._frame_at(int(i)))
            for i in indices
        )
        col = auto_collider_for_frames(
            items, force_kind=force, scales=self._hitbox_union_scales(indices),
        )
        if lockable and not self._hitbox_locked_kind and col and col.kind in _AUTO_KIND_FORCE:
            self._hitbox_locked_kind = _AUTO_KIND_FORCE[col.kind]
        if spec == "clip":
            self._hitbox_baked_key = self._clip_hitbox_key()
        self._apply_source_collider(col, ref)

    def _sync_clip_hitbox(self) -> None:
        """Rebake when ``hitbox_from="clip"`` and the playing clip (or still) changed."""
        if self._hitbox_from != "clip":
            return
        if self._hitbox_kind not in _HITBOX_CHOICES:
            return
        key = self._clip_hitbox_key()
        if self._auto_baked and self._hitbox_baked_key == key:
            return
        self._invalidate_auto_bake()
        if getattr(self, "_collidable", False):
            self._ensure_auto_baked()

    def _sync_auto_hitbox_frame(self) -> None:
        """Rebake per playhead cell (``"each"``) or on clip switch (``"clip"``)."""
        spec = self._hitbox_from
        if spec == "each":
            if self._hitbox_kind not in _HITBOX_CHOICES:
                return
            if not self._play_frames:
                return
            idx = self._current_frame_index()
            if int(self._hitbox_frame) == int(idx):
                return
            from .entity import _bump_collision_epoch
            _bump_collision_epoch(self)
            self._ensure_auto_baked()
            return
        if spec == "clip":
            if self._play_frames:
                self._current_frame_index()
            self._sync_clip_hitbox()

    def _hitbox_pose_src(self) -> Tuple[float, float]:
        """Source size of the cell the baked locals are fractions of.

        Frozen bakes keep the reference cell. ``hitbox_from="each"`` rebakes
        per cell, and each cell draws at its own size, so the pose follows the
        baked cell.
        """
        if self._hitbox_from == "each" and self._play_frames:
            fr = self._sheet._frame_at(int(self._hitbox_frame))
            return float(fr.src_w) or 1.0, float(fr.src_h) or 1.0
        return float(self._hitbox_ref_src_w) or 1.0, float(self._hitbox_ref_src_h) or 1.0

    def _hitbox_pose_wh(self) -> Tuple[float, float]:
        """World size baked hitbox locals map onto.

        The baked cell's pixels at the sprite's one scale (``_du_per_px``).
        ``play()`` changes ``width`` / ``height`` to the current cell, but not
        the scale, so a frozen body collider does not grow, shrink or sink when
        a clip with a different canvas plays.
        """
        s = abs(float(self._scale))
        px_w, px_h = self._hitbox_pose_src()
        kx, ky = self._du_per_px()
        return px_w * kx * s, px_h * ky * s


# Clips with a finite ``loops=`` (they end, and may switch to ``next=``), by
# the world time they end: ``(due, seq, weakref)``. ``settle_clip_ends`` reads
# the due ones in the simulation, so the end and the ``next=`` switch (with its
# size write) never happen first inside a draw (review 2026-10-09 S7-7). A
# heap, not a walk: a frame with nothing due costs one compare (a walk of 300
# playing sprites cost 5 % of the frame). A stale entry (the clip changed, the
# time scale moved the end) no longer matches ``sprite._play_due``.
_CLIP_DUE: list = []
_CLIP_SEQ = itertools.count()


def _schedule_clip_end(sp) -> None:
    loops = sp._play_loops
    scale = float(sp._time_scale)
    if loops is None or not sp._play_frames or sp._play_fps <= 0.0 or scale <= 0.0:
        sp._play_due = None             # never ends, or frozen (rescheduled on thaw)
        return
    length = _clip_period(len(sp._play_frames), sp._play_yoyo) * loops / sp._play_fps
    due = sp._play_t0 + length / scale
    sp._play_due = due
    heapq.heappush(_CLIP_DUE, (due, next(_CLIP_SEQ), weakref.ref(sp)))


_CLIP_COMPACT_AT = 256


def _compact_clip_due() -> None:
    """Drop entries of dead sprites and stale ends (a spawned sprite with a
    long finite clip, destroyed early, would otherwise sit until its end)."""
    global _CLIP_COMPACT_AT
    live = []
    for entry in _CLIP_DUE:
        sp = entry[2]()
        if sp is not None and not getattr(sp, "_destroyed", False) and sp._play_due == entry[0]:
            live.append(entry)
    heapq.heapify(live)
    _CLIP_DUE[:] = live
    _CLIP_COMPACT_AT = max(256, 2 * len(live))


def settle_clip_ends() -> None:
    """Frame body, after the process tick: finish due clip ends / switches."""
    if not _CLIP_DUE:
        return
    if len(_CLIP_DUE) > _CLIP_COMPACT_AT:
        _compact_clip_due()
    now = _world_time()
    early = now + 1e-6                  # the playhead's own tolerance decides
    again = []
    while _CLIP_DUE and _CLIP_DUE[0][0] <= early:
        entry = heapq.heappop(_CLIP_DUE)
        sp = entry[2]()
        if sp is None or getattr(sp, "_destroyed", False) or sp._play_due != entry[0]:
            continue
        if not sp._play_frames or sp._play_loops is None:
            sp._play_due = None         # stopped by another writer (frame =, svg =)
            continue
        sp._current_frame_index()
        if sp._play_due == entry[0] and sp._play_frames:
            again.append(entry)         # not over by the playhead's count yet
    for entry in again:
        heapq.heappush(_CLIP_DUE, entry)


class Sprite(_HitboxBakeMixin, Graphic, PaintState):
    """Image-body actor. Not a Shape — ``isinstance(sprite, Shape)`` is False.

    Source is pixels; ``width`` / ``height`` / ``size`` are design units.
    ``scale`` remains pose zoom about the pivot. ``play`` is a look (survives
    mode changes). Default collider is ``hitbox="auto"`` (baked on collision enroll).

    ``Sprite("potion.png")`` is a still. Anything multi-frame / shared / clipped
    goes through ``Sheet``. ``Sprite(sheet)`` autoplays when the catalog has
    exactly one clip (omit ``frame=`` to animate; pass ``frame=`` to stay still).
    ``play(clip)`` runs a named clip already registered on the Sheet.

    Overlay looks (``Glow``, ``Shadow``, ``Halo``, ``Tail``, ``Beat``) and
    ellipse force-fields (``ElectricField``, ``ElectricBolt``, ``Shield``) may
    be assigned to ``.visual``. Body-replacing looks raise ``TypeError``.

    ``art_angle`` is the bitmap nose in degrees (0 = +x, 90 = +y), before flip.
    ``.angle`` is world heading (where the painted front points). Draw,
    hit-test, and colliders use ``angle - art'`` (``art'`` = ``art_angle``
    reflected by ``flip_*``). Toggling ``flip_x`` / ``flip_y`` rewrites
    ``angle`` so heading stays aligned with the mirror. Construct seeds
    ``angle`` to ``rest_heading``. Use ``reset_rotation()`` to untilt
    (also clears visual-only ``tilt``). ``tilt`` leans the drawn cell without
    rotating the collider — use it on ramps instead of writing ``.angle``.
    One ``art_angle`` per sprite (clips share it).

    Repeated ``Sprite("shot.png")`` shares one decoded image and one interned
    catalog. ``clone()`` is optional sugar for “another one like this”
    (constructor + ``setup()``, then a look snapshot) — not required for
    fire-rate performance. ``Sheet`` is for clips / atlas / many frames.

    Args:
        source: Image file (still) or a ``Sheet``.
        center: Pivot position (with a bottom-anchored Sheet, the feet).
        width: Width in design units (alone: keeps the aspect; with ``height``:
            stretches).
        height: Height in design units.
        size: Longer side in design units (keeps the aspect; not with ``width`` /
            ``height``).
        frame: Still cell: index or atlas name; wins over autoplay.
        hitbox_shape: The main hitbox's shape: ``"auto"`` (default) · ``"rect"`` ·
            ``"ellipse"`` · ``"circle"`` · ``"hull"`` (then ``sprite.hitbox.shape``).
        hitbox_source: Which art the main hitbox is measured on: a frame, a clip,
            ``"all"`` · ``"clip"`` · ``"each"`` (then ``sprite.hitbox.source``).
        hitbox_anchor: Point that stays put when the main hitbox is scaled
            (``"center"``, ``"bottom"``, …; then ``sprite.hitbox.anchor``).
        hitbox_scale: Shrink / stretch the main hitbox: a number or ``(sx, sy)``
            (then ``sprite.hitbox.scale``).
        shield_scale: Size of the Shield / Electric* envelope around the art (default
            1.4).
        offset: Shift ``(dx, dy)`` of the picture and collider from ``center``.
        visual: A look (``Halo()``, ``Metal()``, …).
        group: Group tag(s).
        flip_x: Mirror left-right.
        flip_y: Mirror up-down.
        art_angle: Heading the image is drawn facing, in degrees (so angle 0 means
            “facing +x”).
        angle: Heading at construction — where the painted front points, in
            degrees (default: ``rest_heading``, so the sprite appears as drawn).
        box: Fit into a Box (keeps the image aspect).
        layer: Draw layer (default ``"default"``).
    """

    _is_sprite_body = True
    _clone_takes_frame = True       # clone(frame=) picks the copy's sheet frame

    # The main hitbox's knobs live on ``sprite.hitbox`` (a Hitbox). The old
    # flat names would otherwise become ink and silently do nothing.
    _RETIRED_ATTRS = {
        "hitbox_from": "sprite.hitbox_from is now sprite.hitbox.source "
                       "(Sprite(hitbox_source=…) when constructing).",
        "hitbox_source": "the main hitbox's source is sprite.hitbox.source "
                         "(hitbox_source= is the constructor keyword).",
        "hitbox_shape": "the main hitbox's shape is sprite.hitbox.shape "
                        "(hitbox_shape= is the constructor keyword).",
        "hitbox_anchor": "sprite.hitbox_anchor is now sprite.hitbox.anchor "
                         "(Sprite(hitbox_anchor=…) when constructing).",
        "hitbox_scale": "sprite.hitbox_scale is now sprite.hitbox.scale "
                        "(Sprite(hitbox_scale=…) when constructing).",
    }

    # Leaf slots: Entity/Graphic privates + Sprite-specific. (Cannot slot
    # Entity/Graphic bases — MI with PaintState would layout-conflict.)
    __slots__ = (
        '_scenacanvas', '_visible', '_rotation', '_scale', '_reg_key', 'group',
        '_layer',
        '_clickable', '_draggable', '_droppable', '_wheel_rotate',
        '_on_click', '_on_drag_to', '_on_drag_over', '_on_drop_by',
        '_on_hover', '_on_hover_exit',
        '_pointer_hover', '_pointer_pressed',
        '_collidable', '_collider', '_collision_opt_out', '_time_scale',
        '_active', '_active_saved_visible', '_active_saved_collidable',
        '_mode', '_mode_time', 'model', '_ink',
        '_on_update', '_on_destroy', '_mode_script', '_frozen_warned', '_mode_idle_from',
        '_actor_constructed',
        '_geom_path', '_geom_path_key', '_tx_state',
        '_collision_epoch',
        '_plain_blit',
        '_draw_index',
        '_sheet',
        '_owns_sheet',
        '_placeholder',
        '_offset_x',
        '_offset_y',
        '_hitbox_kind',
        '_hitbox_from',
        '_hitbox_anchor',
        '_hitbox_scale',
        '_shield_scale',
        '_shield_env',
        '_shield_env_key',
        '_hitbox_boxes',
        '_hitbox_circle',
        '_hitbox_circles',
        '_hitbox_ellipse',
        '_hitbox_ellipses',
        '_hitbox_poly',
        '_hitbox_base_boxes',
        '_hitbox_base_circle',
        '_hitbox_base_circles',
        '_hitbox_base_ellipse',
        '_hitbox_base_ellipses',
        '_hitbox_base_poly',
        '_hitbox_local_radius',
        '_hitbox_extent_x',
        '_hitbox_extent_y',
        '_hitbox_extent_pose',
        '_hitbox_frame',
        '_hitbox_locked_kind',
        '_hitbox_baked_key',
        '_hitbox_parts',
        '_hitbox_claims',
        '_auto_baked',
        '_frame',
        '_construct_frame',
        '_hitbox_ref_src_w',
        '_hitbox_ref_src_h',
        '_ref_src_w',
        '_ref_src_h',
        '_size_intent',
        '_size_intent_value',
        '_play_name',
        '_play_frames',
        '_play_fps',
        '_play_yoyo',
        '_play_loops',
        '_play_next',
        '_play_t0',
        '_play_frozen_elapsed',
        '_play_min_hold',
        '_play_resume_cache',
        '_blit_paint',
        '_blit_color_filter',
        '_blit_gray_cf',
        '_blit_hue_live',
        '_alpha',
        '_saved_alpha',
        '_src_rect_cache',
        '_blit_plan',
        '_flip_x',
        '_flip_y',
        '_art_angle',
        '_tilt',
        '_tilt_mode',
        '_tilt_contact_point',
        '_tilt_contact_angle',
        '_tilt_contact_normal',
        '_tilt_contact_side',
        '_frame_fx_warm_key',
        '__weakref__',
    )

    center = ContainerSlot(Point)
    width = ScalarSlot(magnitude=True, hint=HINT_EXTENT)
    height = ScalarSlot(magnitude=True, hint=HINT_EXTENT)
    # Merged look defaults from ``class X(Sprite, source=..., height=...)``.
    _sprite_defaults: Dict[str, Any] = {}
    # Unknown keyword (``Sprite("a.png", fps=6)``): the actor wrapper names the fix.
    _call_hints = _SPRITE_CATALOG_HINTS

    @classmethod
    def _class_keywords(cls) -> frozenset:
        return frozenset(_SPRITE_DEFAULT_KEYS)

    def __init_subclass__(cls, **kwargs):
        incoming: Dict[str, Any] = {}
        unexpected: Dict[str, Any] = {}
        for key in list(kwargs):
            if key in _SPRITE_DEFAULT_KEYS:
                incoming[key] = kwargs.pop(key)
            elif key in _SPRITE_PLACEMENT_KEYS:
                raise TypeError(
                    f"{key}= is instance placement, not a class default. "
                    f"Pass {key}= when constructing {cls.__name__}(...)."
                )
            else:
                unexpected[key] = kwargs.pop(key)
        _reject_unexpected_sprite_kwargs(cls.__name__, unexpected, class_kw=True)
        merged: Dict[str, Any] = {}
        for base in cls.__mro__[1:]:
            base_defs = getattr(base, "_sprite_defaults", None)
            if base_defs:
                merged = dict(base_defs)
                break
        merged.update(incoming)
        cls._sprite_defaults = merged
        super().__init_subclass__(**kwargs)

    def __init__(
        self,
        source: Union[str, Sheet, None] = None,
        *more_files: str,
        center: Optional[GeneralPoint] = None,
        width: Any = _OMIT,
        height: Any = _OMIT,
        size: Any = _OMIT,
        frame: Any = _OMIT,
        hitbox_shape: Any = _OMIT,
        hitbox_source: Any = _OMIT,
        hitbox_anchor: Any = _OMIT,
        hitbox_scale: Any = _OMIT,
        shield_scale: Any = _OMIT,
        offset: Any = _OMIT,
        visual: Any = _OMIT,
        group: Any = _OMIT,
        flip_x: Any = _OMIT,
        flip_y: Any = _OMIT,
        art_angle: Any = _OMIT,
        angle: Any = _OMIT,
        box: Any = _OMIT,
        layer: Any = _USE_LAYER_DEFAULT,
    ):
        defaults = getattr(type(self), "_sprite_defaults", None) or {}

        def _take(key: str, value: Any, ctor_default: Any) -> Any:
            if value is not _OMIT:
                return value
            if key in defaults:
                return defaults[key]
            return ctor_default

        if more_files:
            raise TypeError(
                "Sprite takes one still file or a Sheet. For several frames write "
                'Sheet("a.png", "b.png") then Sprite(sheet).'
            )

        if source is None and "source" in defaults:
            source = defaults["source"]

        width = _take("width", width, None)
        height = _take("height", height, None)
        size = _take("size", size, None)
        frame_given = frame is not _OMIT or "frame" in defaults
        frame = _take("frame", frame, 0)
        hitbox = _take("hitbox_shape", hitbox_shape, None)
        hitbox_from = _take("hitbox_source", hitbox_source, None)
        hitbox_anchor = _take("hitbox_anchor", hitbox_anchor, "center")
        hitbox_scale = _take("hitbox_scale", hitbox_scale, 1.0)
        shield_scale = _take("shield_scale", shield_scale, _SPRITE_SHIELD_SCALE)
        offset = _take("offset", offset, None)
        visual = _take("visual", visual, None)
        group = _take("group", group, None)
        from .validate import expect_bool
        flip_x = expect_bool(_take("flip_x", flip_x, False), "flip_x")
        flip_y = expect_bool(_take("flip_y", flip_y, False), "flip_y")
        art_angle = _parse_art_angle(_take("art_angle", art_angle, 0.0))
        box = None if box is _OMIT else box
        if box is not None and center is not None:
            raise TypeError(
                "Sprite(box=) cannot mix with center= — box= is its own constructor family"
            )

        # Paint before Graphic so look/style slots exist; bitmap body sentinel.
        self._alpha = 1.0
        PaintState.__init__(self)
        self._fill = SPRITE_BODY
        self._line = None
        self._look_identity = None
        self._is_fill_paint_dirty = True
        self._is_line_paint_dirty = True

        Graphic.__init__(self, layer=layer, group=group)
        try:
            self._init_sprite_body(
                source,
                center=center, width=width, height=height, size=size,
                frame=frame, frame_given=frame_given, hitbox=hitbox,
                hitbox_from=hitbox_from, hitbox_anchor=hitbox_anchor,
                hitbox_scale=hitbox_scale, shield_scale=shield_scale,
                offset=offset, visual=visual,
                flip_x=flip_x, flip_y=flip_y, art_angle=art_angle,
                box=box,
            )
            if angle is not _OMIT:
                self._init_heading(angle)
            pending = self.__dict__.pop('_box_formula_pending', None)
            if pending is not None:
                from .box import link_sprite_box_formula
                link_sprite_box_formula(self, *pending, angle_given=angle is not _OMIT)
        except BaseException:
            try:
                self.destroy()
            except Exception:
                pass
            raise

    def _relation_unlinked(self, link) -> None:
        """A part's link was removed (``Container.unlink``): a box-linked
        sprite lets go of its region as a whole (``box.box_fit_unlinked``)."""
        if self.__dict__.get('_box_fit') is not None:
            from .box import box_fit_unlinked
            box_fit_unlinked(self, link)

    def _drop_box_fit(self) -> None:
        """The relation to a ``box=<formula>`` region goes as a whole
        (``box.drop_box_fit``; Box Design, "Fit")."""
        from .box import drop_box_fit
        drop_box_fit(self)

    def _init_sprite_body(
        self,
        source,
        *,
        center, width, height, size,
        frame, frame_given, hitbox,
        hitbox_from, hitbox_anchor,
        hitbox_scale, shield_scale,
        offset, visual,
        flip_x, flip_y, art_angle,
        box=None,
    ) -> None:
        sheet = _bind_source(source)
        self._sheet = sheet
        self._owns_sheet = not bool(getattr(sheet, "_shared", False))
        self._placeholder = bool(sheet._placeholder)
        ox, oy = _parse_offset(offset)
        self._offset_x = ox
        self._offset_y = oy
        self._flip_x = flip_x
        self._flip_y = flip_y
        self._art_angle = art_angle
        self._tilt = 0.0
        self._tilt_mode = "angle"
        self._tilt_contact_point = None
        self._tilt_contact_angle = 0.0
        self._tilt_contact_normal = None
        self._tilt_contact_side = None
        # Seed heading to rest (draw_angle = 0). Keep the construct epoch clean.
        object.__setattr__(
            self,
            "_rotation",
            _rest_heading_from_pose(art_angle, flip_x=flip_x, flip_y=flip_y),
        )
        self._hitbox_kind = "auto"
        self._hitbox_from: Union[int, str] = 0
        self._hitbox_anchor = _parse_hitbox_anchor(hitbox_anchor)
        self._hitbox_scale = _parse_hitbox_scale(hitbox_scale)
        self._shield_scale = _parse_shield_scale(shield_scale)
        self._shield_env: Optional[Tuple[float, float, float, float]] = None
        self._shield_env_key: Optional[tuple] = None
        self._hitbox_boxes: Tuple[Tuple[float, float, float, float], ...] = ()
        self._hitbox_circle: Optional[Tuple[float, float, float]] = None
        self._hitbox_circles: Tuple[Tuple[float, float, float], ...] = ()
        self._hitbox_ellipse: Optional[Tuple[float, float, float, float, float]] = None
        self._hitbox_ellipses: Tuple[Tuple[float, float, float, float, float], ...] = ()
        self._hitbox_poly: Tuple[Tuple[float, float], ...] = ()
        self._hitbox_base_boxes: Tuple[Tuple[float, float, float, float], ...] = ()
        self._hitbox_base_circle: Optional[Tuple[float, float, float]] = None
        self._hitbox_base_circles: Tuple[Tuple[float, float, float], ...] = ()
        self._hitbox_base_ellipse: Optional[Tuple[float, float, float, float, float]] = None
        self._hitbox_base_ellipses: Tuple[Tuple[float, float, float, float, float], ...] = ()
        self._hitbox_base_poly: Tuple[Tuple[float, float], ...] = ()
        self._hitbox_local_radius = 0.0
        self._hitbox_extent_x = 0.0
        self._hitbox_extent_y = 0.0
        self._hitbox_extent_pose = None
        self._hitbox_frame = 0
        self._hitbox_locked_kind: Optional[str] = None
        self._hitbox_baked_key = None
        self._hitbox_parts = ()
        self._hitbox_claims = None
        self._auto_baked = False
        self._construct_frame = 0
        self._hitbox_ref_src_w = 1.0
        self._hitbox_ref_src_h = 1.0

        try:
            if not frame_given and sheet._cycles:
                # No frame=: start on the first cell of the sheet's first
                # clip. ``height=`` / ``size=`` fix the sprite's one scale on
                # this cell, so it must be the art the author means — not an
                # arbitrary cell 0 of a packed atlas (a laser next to the ship).
                first_clip = next(iter(sheet._cycles.values()))
                frame_idx = int(first_clip[0][0]) if first_clip[0] else 0
            else:
                frame_idx = sheet.frame_index(frame)
        except ValueError:
            key = as_payload(frame)
            if not isinstance(key, str):
                raise
            _warn_unknown_frame(sheet, key)
            sheet = _labeled_placeholder_sheet(os.path.basename(key) or key)
            self._sheet = sheet
            self._owns_sheet = not bool(getattr(sheet, "_shared", False))
            self._placeholder = True
            frame_idx = 0
        fr0 = sheet._frame_at(frame_idx)
        px_w, px_h = fr0.src_w, fr0.src_h
        inherit_angle = 0.0
        box_formula = None
        if box is not None:
            from .box import is_box_formula, sprite_size_from_box
            asked = (width, height, size)
            if is_box_formula(box):
                # box=<formula>: build in the first region like a plain box=,
                # then link center / heading / scale (``_link_box_formula``).
                box_formula = box
                box = box_formula()
            width, height, size, center, inherit_angle = sprite_size_from_box(
                box, px_w, px_h, width=width, height=height, size=size,
            )
        pixel_size = getattr(sheet, "_pixel_size", None)
        if (
            box is not None
            and size is None
            and width == 0.0
            and height == 0.0
        ):
            if box_formula is not None:
                # A collapsed first region: build at the default size and
                # let the linked scale (0 now) grow it with the region.
                du_w, du_h = _fit_size(px_w, px_h, width=None, height=None, size=None)
            else:
                du_w, du_h = 0.0, 0.0
        elif (
            pixel_size is not None
            and width is None and height is None and size is None
        ):
            # ``Sheet(pixel_size=)``: the art sets the scale — each PNG pixel is
            # ``pixel_size`` design units; no per-sprite default size.
            du_w, du_h = float(px_w) * pixel_size, float(px_h) * pixel_size
        else:
            du_w, du_h = _fit_size(px_w, px_h, width=width, height=height, size=size)

        (dcx, dcy), _unit = _default_pose(self._scenacanvas)
        with self._batch_update():
            if center is None:
                self.center._takein((dcx, dcy))
            else:
                _init_composite(self.center, center)
            self.width = du_w
            self.height = du_h
        rest = float(self._rotation)
        if inherit_angle:
            # The art lies along the region (contain fits it to the region's
            # axes): the drawn angle is the region's, so the heading turns
            # from rest. Writing the region angle as the heading drew a
            # flipped sprite (rest 180) upside down unless the angle was
            # exactly 0 (SF1 in Testing Design).
            self.rotate_to(rest + inherit_angle)
        if box_formula is not None:
            w_ask, h_ask, s_ask = asked
            self.__dict__['_box_formula_pending'] = (
                box_formula, px_w, px_h, w_ask, h_ask, s_ask, du_w, du_h, rest)

        self._frame = int(frame_idx)
        self._construct_frame = int(frame_idx)
        self._hitbox_from = _parse_hitbox_from(
            hitbox_from, sheet, construct_frame=frame_idx, what="hitbox_source",
        )
        self._hitbox_ref_src_w = float(px_w)
        self._hitbox_ref_src_h = float(px_h)
        self._ref_src_w = float(px_w)
        self._ref_src_h = float(px_h)
        intent, intent_value = _parse_size_intent(width, height, size)
        self._size_intent = intent
        self._size_intent_value = intent_value
        self._play_name: Optional[str] = None
        self._play_frames: Tuple[int, ...] = ()
        self._play_fps = 0.0
        self._play_yoyo = False
        self._play_loops: Optional[int] = None  # None = forever
        self._play_next: Optional[str] = None
        self._play_t0 = 0.0
        self._play_frozen_elapsed = 0.0
        self._play_due = None           # world time a finite clip ends
        self._play_min_hold = 0.0
        self._play_resume_cache: Dict[str, float] = {}
        self._blit_paint = _BLIT_PAINT
        self._blit_color_filter = None
        self._blit_gray_cf = None
        self._blit_hue_live = None
        self._alpha = 1.0
        self._src_rect_cache = None
        object.__setattr__(self, "_blit_plan", None)
        self._frame_fx_warm_key = None

        self._set_hitbox(hitbox, what="hitbox_shape")

        if visual is not None:
            self.visual = visual

        clips = list(sheet._cycles)
        if not frame_given and len(clips) == 1:
            self.play(clips[0])

    # --- size / frame / hitbox ------------------------------------------------

    @property
    def size(self) -> float:
        """Longer side in design units."""
        w = abs(self.width)
        h = abs(self.height)
        return max(w, h)

    @size.setter
    def size(self, value) -> None:
        longer = _positive_number(value, what="size", exclusive=False)
        # Both sides before either write: a linked ``height`` refused after
        # ``width`` had landed (review 2026-10-09 S7-5).
        from .shapes import _ensure_writable
        _ensure_writable(self["width"], "size =")
        _ensure_writable(self["height"], "size =")
        w = abs(self.width)
        h = abs(self.height)
        if w <= 0.0 or h <= 0.0:
            # Collapsed: the current box has no aspect left, the cell still has
            # (PB14: size = 0 then size = 20 gave a square).
            rw = float(getattr(self, "_ref_src_w", 0.0) or 0.0)
            rh = float(getattr(self, "_ref_src_h", 0.0) or 0.0)
            if rw > 0.0 and rh > 0.0:
                w, h = rw, rh
        if w <= 0.0 and h <= 0.0:
            self.width = longer
            self.height = longer
        elif w >= h:
            aspect = (h / w) if w else 1.0
            self.width = longer
            self.height = longer * aspect
        else:
            aspect = (w / h) if h else 1.0
            self.height = longer
            self.width = longer * aspect
        # ``play()`` refits from this intent. Leaving the construct intent
        # would snap the next clip back to the size passed at init.
        self._size_intent = "size"
        self._size_intent_value = longer
        self._invalidate_shield_envelope()
        from .entity import _bump_collision_epoch
        _bump_collision_epoch(self)

    @property
    def frame(self) -> int:
        """Current cell index (``play`` may advance this).

        Writing ``sprite.frame = …`` selects that cell and **stops** playback
        (clears the active clip). Use ``play`` again to resume animating.
        """
        return self._current_frame_index()

    @frame.setter
    def frame(self, value) -> None:
        idx = self._sheet.frame_index(value)
        # A linked size refuses before the clip stops (as ``play()`` does:
        # PB1; review 2026-10-09 S7-6).
        self._gate_clip_size((int(idx),), "frame =")
        self._play_name = None
        self._play_frames = ()
        self._play_min_hold = 0.0
        self._frame = int(idx)
        self._apply_size_intent(self._sheet._frame_at(self._frame))
        from .entity import _bump_collision_epoch
        _bump_collision_epoch(self)
        self._sync_clip_hitbox()

    # Main hitbox knobs: written through ``sprite.hitbox.source`` / ``.anchor``
    # / ``.scale`` (``hitbox.py`` ``_MainHitbox``) and the constructor.
    def _set_hitbox_source(self, value) -> None:
        """Which art defines the main hitbox (frame, clip, ``"all"``, ``"each"``, ``"clip"``)."""
        spec = _parse_hitbox_from(
            value, self._sheet, construct_frame=int(self._construct_frame),
            what="source",
        )
        if spec == self._hitbox_from:
            return
        self._hitbox_from = spec
        self._invalidate_auto_bake()
        if getattr(self, "_collidable", False):
            self._ensure_auto_baked()

    def _set_hitbox_anchor(self, value) -> None:
        """Fixed point for the main hitbox's ``scale``, replacement, and ``.tilt``.

        A preset string round-trips as that string. An ``(ax, ay)`` pair
        round-trips as floats (y-up; ``(0, 0)`` is center, ``(0, -1)`` is bottom).
        """
        key = _parse_hitbox_anchor(value, what="anchor")
        if key == self._hitbox_anchor:
            return
        self._hitbox_anchor = key
        if self._auto_baked:
            self._apply_hitbox_shaping()
        from .entity import _bump_collision_epoch
        _bump_collision_epoch(self)

    def _set_hitbox_scale(self, value) -> None:
        """Main hitbox margin ``(sx, sy)``: a scalar or a pair."""
        pair = _parse_hitbox_scale(value, what="scale")
        if pair == self._hitbox_scale:
            return
        self._hitbox_scale = pair
        if self._auto_baked:
            self._apply_hitbox_shaping()
        from .entity import _bump_collision_epoch
        _bump_collision_epoch(self)

    def showing(self, frames) -> bool:
        """True while the cell on screen is one of ``frames``.

        ``frames``: a clip name (its cells), a frame index, a frame name, or a
        tuple / list mixing them. It goes by cell, so it stays right through
        ``yoyo``, ``resume=``, ``next=`` and an interrupted clip; a cell that
        two clips share counts in both. Link a hitbox to the attack frames
        with ``hb["active"] @= lambda: sprite.showing(...)``.
        """
        cells = _parse_frame_selector(frames, self._sheet)
        return int(self._still_hitbox_index()) in cells

    def add_hitbox(
        self,
        *,
        group=None,
        shape=_ADD_HITBOX_UNSET,
        source=_ADD_HITBOX_UNSET,
        anchor=_ADD_HITBOX_UNSET,
        scale=_ADD_HITBOX_UNSET,
        active=True,
        px_rect=None,
        px_circle=None,
        **retired,
    ):
        """Add a detection-only hitbox part; returns a :class:`Hitbox`.

        Same four knobs as the main hitbox (``sprite.hitbox``), but ``source``
        defaults to ``"each"`` (it follows the current cell) and the part
        follows the paint, ``tilt`` included. ``group=`` names the groups this
        hitbox answers for: the sprite joins them, and collision uses this
        hitbox for them instead of the main one. ``resolve()`` never uses a
        part.

        ``px_rect=(x, y, w, h)`` / ``px_circle=(x, y, r)`` place one shape by
        hand, in the frame's pixels as the image editor shows them (top-left
        origin, y down); it stays on the drawing. Not with the art knobs.
        Link ``active`` to the animation with
        ``hb["active"] @= lambda: sprite.showing(...)``.
        """
        from .hitbox import Hitbox, _RETIRED_KNOBS
        from .entity import _author_site, _refuse_if_destroyed
        if retired:
            name = sorted(retired)[0]
            new = _RETIRED_KNOBS.get(name)
            if new is not None and "." not in new:
                raise TypeError(
                    f"add_hitbox({name}=) is now add_hitbox({new}=) — a hitbox's "
                    "knobs drop the hitbox_ prefix (shape= / source= / anchor= / scale=)."
                )
            raise TypeError(
                f"add_hitbox() got an unexpected keyword argument {name!r}. "
                "Knobs: group=, shape=, source=, anchor=, scale=, active=, "
                "px_rect=, px_circle=."
            )
        _refuse_if_destroyed(self, "add_hitbox")   # DestroyedError (A7; was RuntimeError)
        return Hitbox._make(
            self,
            group=group,
            shape=shape,
            source=source,
            anchor=anchor,
            scale=scale,
            active=active,
            px_rect=px_rect,
            px_circle=px_circle,
            site=_author_site(),
        )

    def remove_hitbox(self, part) -> "Sprite":
        """Remove a part made by ``add_hitbox``. The sprite leaves the groups
        the part put it in; groups it was in on its own stay (HP13). Refused
        on a destroyed sprite (HP12: it was silent)."""
        _refuse_if_destroyed(self, "remove_hitbox")
        if part is self.__dict__.get("_main_hitbox_view"):
            raise TypeError(
                "the main hitbox is not removable; switch it off with "
                "sprite.hitbox.active = False (extra hitboxes keep detecting)."
            )
        if part not in self._hitbox_parts:
            raise ValueError(f"{part!r} is not a hitbox of this sprite")
        part._detach()
        self._hitbox_parts = tuple(p for p in self._hitbox_parts if p is not part)
        return self

    @property
    def hitboxes(self) -> tuple:
        """Every hitbox, main first: ``(sprite.hitbox, *parts)``. Read-only."""
        return (self.hitbox,) + tuple(self._hitbox_parts)

    @hitboxes.setter
    def hitboxes(self, value) -> None:
        raise AttributeError(
            "sprite.hitboxes lists every hitbox (main first) and is read-only. "
            "Add one with sprite.add_hitbox(...), remove one with "
            "sprite.remove_hitbox(hb)."
        )

    def _hitbox_part_colliders(self) -> tuple:
        """Registered part colliders (engine: destroy / park / ``collidable``)."""
        return tuple(
            p._collider for p in (getattr(self, "_hitbox_parts", None) or ())
            if p._collider is not None
        )

    def _retire_hitbox_parts(self) -> None:
        """``collidable = False`` / park: every part leaves collision (exits fire)."""
        for p in getattr(self, "_hitbox_parts", None) or ():
            p._retire_collider()

    def _on_sheet_swapped(self) -> None:
        """A new catalog replaced ``_sheet``: body and parts rebake lazily."""
        self._auto_baked = False
        self._hitbox_locked_kind = None
        self._hitbox_baked_key = None
        from .entity import _bump_collision_epoch
        _bump_collision_epoch(self)
        for p in self._hitbox_parts:
            p._invalidate_auto_bake()

    @property
    def shield_scale(self) -> float:
        """Shield costume ellipse scale vs the silhouette envelope (default 1.4)."""
        return float(self._shield_scale)

    @shield_scale.setter
    def shield_scale(self, value) -> None:
        self._shield_scale = _parse_shield_scale(value)
        # The shield oval is a draw-box input (the cull keys its box on the
        # pose revision; Canvas Design, "Offscreen culling").
        bump_pose_rev(self)

    def _set_hitbox(self, value, what: str = "shape") -> None:
        # Omitted hitbox: atlas JSON/XML boxes if present, else default auto.
        if value is None:
            self._hitbox_kind = "auto"
            self._invalidate_auto_bake()
            if getattr(self, "_collidable", False):
                self._ensure_auto_baked()
            return

        kind = _parse_hitbox(value, what=what)
        self._hitbox_kind = kind
        self._invalidate_auto_bake()
        if getattr(self, "_collidable", False):
            self._ensure_auto_baked()

    @property
    def offset(self) -> Tuple[float, float]:
        """Shift ``(dx, dy)`` of the picture and its collider from ``center``, in design units. Turns and flips with the Sprite."""
        return (self._offset_x, self._offset_y)

    @offset.setter
    def offset(self, value) -> None:
        self._offset_x, self._offset_y = _parse_offset(value)
        from .entity import _bump_collision_epoch
        _bump_collision_epoch(self)

    @property
    def alpha(self) -> float:
        """Sticky body opacity for the image blit, in ``[0, 1]`` (default 1.0).

        Baked into ``_blit_paint`` at set-time. Still plain-blit eligible.
        Composes multiplicatively with ``fade_in`` / ``fade_out``. Does not
        fade ``_replaces_sprite_body`` fills or Shield / Electric* envelopes.
        """
        return self._alpha

    @alpha.setter
    def alpha(self, value: float) -> None:
        _refuse_if_destroyed(self, "alpha")
        from .validate import alpha01
        a = alpha01(value, "Sprite alpha")
        if abs(a - self._alpha) < 1e-6:
            return
        self._alpha = a
        self._rebuild_blit_paint()

    def set_alpha(self, alpha: float) -> "Sprite":
        """Set body opacity and return ``self`` (does not touch fill/line)."""
        self.alpha = alpha
        return self

    def save_visual(self) -> "Sprite":
        """``PaintState.save_visual`` plus the body ``alpha`` (a Sprite channel the
        PaintState snapshot does not hold; restore reset it to 1.0, HP4)."""
        if getattr(self, "_saved_visual", None) is None:
            self._saved_alpha = self._alpha
        PaintState.save_visual(self)
        return self

    def restore_visual(self) -> "Sprite":
        """Put back the appearance from :meth:`save_visual`, body ``alpha`` included."""
        had = getattr(self, "_saved_visual", None) is not None
        PaintState.restore_visual(self)
        if had:
            self.alpha = getattr(self, "_saved_alpha", self._alpha)
        return self

    @property
    def rest_heading(self) -> float:
        """Heading when the bitmap appears as drawn (``draw_angle == 0``).

        Reflects ``art_angle`` under the current ``flip_*`` flags. Nave
        ``art_angle=90`` → ``90``; ninja ``art_angle=0`` + ``flip_x`` → ``180``.
        """
        return _rest_heading_from_pose(
            self._art_angle,
            flip_x=self._flip_x,
            flip_y=self._flip_y,
        )

    @property
    def tilt(self) -> float:
        """Visual-only lean in degrees. Does not rotate the collider.

        Every spelling rotates the art about the baked ``hitbox_anchor`` and
        leaves ``center`` where the solver put it. The collider is not rotated.

        Float: that angle, until overwritten. Rotation only — no seat.

        ``TouchingContact``: ``slope_angle`` of that contact, until overwritten
        (``tilt = 0`` first each frame, or the last lean sticks in the air).
        When ``side`` is ``"bottom"`` and the anchor is the bottom face, the
        paint also moves along ``normal`` until that anchor lies on the plane
        through ``point``.

        ``"ground"`` / ``AUTO_GROUND``: ``slope_angle`` of one bottom contact;
        ``0`` when none. Same normal-only seat while a bottom contact exists
        and the anchor is the bottom face.
        """
        mode = getattr(self, "_tilt_mode", "angle")
        if mode == "angle":
            return float(self._tilt)
        if mode == "contact":
            return float(getattr(self, "_tilt_contact_angle", 0.0))
        # auto_ground
        c = self._select_ground_contact()
        return float(c.slope_angle) if c is not None else 0.0

    @tilt.setter
    def tilt(self, value) -> None:
        try:
            self._set_tilt(value)
        finally:
            # The paint lean is a draw-box input (the cull keys its box on
            # the pose revision; Canvas Design, "Offscreen culling").
            bump_pose_rev(self)

    def _set_tilt(self, value) -> None:
        from .collision import TouchingContact

        if value is AUTO_GROUND or value == "ground":
            self._tilt_mode = "auto_ground"
            self._tilt_contact_point = None
            self._tilt_contact_angle = 0.0
            self._tilt_contact_normal = None
            self._tilt_contact_side = None
            return

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            from .validate import number
            angle = number(value, "Sprite.tilt angle")
            self._tilt_mode = "angle"
            self._tilt_contact_point = None
            self._tilt_contact_angle = 0.0
            self._tilt_contact_normal = None
            self._tilt_contact_side = None
            self._tilt = angle
            return

        if isinstance(value, TouchingContact):
            self._tilt_mode = "contact"
            self._tilt_contact_point = value.point
            self._tilt_contact_angle = float(value.slope_angle)
            self._tilt_contact_side = value.side
            n = value.normal
            try:
                self._tilt_contact_normal = (float(n.x), float(n.y))
            except Exception:
                self._tilt_contact_normal = None
            # Keep legacy numeric for any code paths that still read it.
            self._tilt = float(value.slope_angle)
            return

        raise TypeError(
            "Sprite.tilt expected a float angle, TouchingContact, or 'ground'. "
            f"Got {type(value).__name__}."
        )

    def reset_rotation(
        self,
        *,
        time: Optional[float] = None,
        speed: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        about=None,
        force: bool = False,
    ):
        """Turn back to the rest heading (``art_angle``) and clear the tilt. The flip stays.

        Args:
            time: seconds to turn (omit for instant), or ``speed=`` in degrees
                per second; then the usual ``ease=`` / ``then=`` / ``on_done=`` /
                ``about=`` / ``force=``.
        """
        tilt_fields = ("_tilt", "_tilt_mode", "_tilt_contact_point", "_tilt_contact_angle",
                       "_tilt_contact_normal", "_tilt_contact_side")
        saved = tuple(getattr(self, f) for f in tilt_fields)
        self._tilt = 0.0
        self._tilt_mode = "angle"
        self._tilt_contact_point = None
        self._tilt_contact_angle = 0.0
        self._tilt_contact_normal = None
        self._tilt_contact_side = None
        try:
            return super().reset_rotation(
                time=time, speed=speed, ease=ease, then=then, on_done=on_done,
                about=about, force=force,
            )
        except BaseException:
            for f, v in zip(tilt_fields, saved):   # a refused turn keeps the tilt (PB12)
                setattr(self, f, v)
            raise

    @property
    def art_angle(self) -> float:
        """Nose of the bitmap in degrees (0 = +x, 90 = +y), before flip.

        ``angle`` is world heading (where the front points). Draw /
        hit-test / colliders use ``angle - art'`` (``art'`` flipped).
        Toggling ``flip_*`` rewrites ``angle``; live ``art_angle`` writes
        do not.
        """
        return float(self._art_angle)

    @art_angle.setter
    def art_angle(self, value) -> None:
        self._art_angle = _parse_art_angle(value)
        from .entity import _bump_collision_epoch
        _bump_collision_epoch(self)

    def _apply_local_flip(self, x: float, y: float) -> Tuple[float, float]:
        """Reflect a pivot-relative local point under ``flip_x`` / ``flip_y``."""
        if self._flip_x:
            x = -x
        if self._flip_y:
            y = -y
        return x, y

    def _flip_local_angle(self, ang: float) -> float:
        """Reflect a local angle (radians) under ``flip_x`` / ``flip_y``.

        H → ``π − α``, V → ``−α``, both → ``α + π`` (mod ``2π``).
        """
        if self._flip_x:
            ang = math.pi - ang
        if self._flip_y:
            ang = -ang
        return ang

    @property
    def visual(self):
        """The look drawn for this Sprite (``Halo()``, ``Metal()``, …), or ``None`` for the plain picture."""
        return getattr(self, "_visual", None)

    @visual.setter
    def visual(self, value) -> None:
        if value is None:
            PaintState.visual.fset(self, None)
            # Restore bitmap-body sentinel if identity had no author fill.
            if is_sprite_body(getattr(self, "_fill", None)) or getattr(self, "_fill", None) is None:
                self._fill = SPRITE_BODY
                self._is_fill_paint_dirty = True
            # Hue is a stamp — do not clear it when clearing costume.
            self._frame_fx_warm_key = None
            self._invalidate_shield_envelope()
            return
        look = coerce_visual(value)
        if look is getattr(self, "_visual", None):
            return
        if not getattr(look, "_allows_sprite", False):
            name = type(look).__name__
            raise TypeError(
                f"Cannot assign {name} as Sprite.visual — body-replacing looks "
                f"would hide the image. Use an overlay / path / material look "
                f"(Halo, Rim, DashRing, Laser, Ink, Metal, Flame, Swell, "
                f"Extrude, …) or ElectricField / ElectricBolt / Shield, or a Shape. "
                f"Stamps: .glow / .shadow / .hue / .gray / .tail. "
                f"Transients like flash() / blink() already work."
            )
        if (getattr(look, "_seed_color", None) is not None
                and not getattr(look, "_sprite_takes_color", True)):
            name = type(look).__name__
            raise TypeError(
                f"{name}(color=…) paints a Shape's body; a Sprite keeps its own "
                f"pixels. Use {name}() on a Sprite, and tint the picture with "
                f"sprite.hue = HueShift(to=…)."
            )
        PaintState.visual.fset(self, look)
        self._warm_frame_fx_for_visual()
        self._warm_shield_envelope_for_visual()

    def look_like(self, other: PaintState) -> "Sprite":
        """Copy appearance; warm FrameFx when the copied visual needs a path/SDF."""
        prev_vis = probe_private(self, "_visual", None)
        PaintState.look_like(self, other)
        self._alpha = float(getattr(other, "_alpha", 1.0))
        from .stamps import apply_gray_stamp, apply_hue_stamp
        apply_hue_stamp(self, getattr(self, "_hue", None))
        apply_gray_stamp(self, getattr(self, "_gray", None))
        self._rebuild_blit_paint()
        fn = getattr(self, "_refresh_plain_blit", None)
        if callable(fn):
            fn()
        if getattr(self, "_visual", None) is prev_vis:
            return self
        self._warm_frame_fx_for_visual()
        self._warm_shield_envelope_for_visual()
        return self

    @property
    def sheet(self) -> Sheet:
        """The Sheet this Sprite plays from. ``Sprite('x.png')`` shares one per file (read-only); build your own Sheet to add clips."""
        return self._sheet

    # --- play (look, not a mode) ---------------------------------------------

    def play(
        self,
        clip: str,
        *,
        loops: Optional[int] = None,
        next: Optional[str] = None,
        min_hold: Optional[float] = None,
        resume: bool = False,
    ) -> "Sprite":
        """Play a named clip from the sheet. Survives mode changes.

        Yoyo mode comes from how the clip was registered (``sheet.clip(..., yoyo=)``).
        Omit ``loops`` to loop forever. ``loops=1`` holds the last frame on a
        wrapping clip, the first frame on a ping-pong clip (or switches via
        ``next=``). ``next=\"idle\"`` is a clip name. Calling ``play`` with the
        same clip that is already running is a no-op (so ``update`` can write
        ``hero.play(\"walk\")`` every frame).

        ``min_hold=`` (seconds, default off) ignores switches away from the
        *current* clip until it has played at least that long — useful when
        ``update`` picks idle/run/jump from a noisy grounded flag.

        ``resume=True`` (default ``False``) continues a clip's remembered
        phase when returning to it, instead of restarting at frame 0. Leave
        off for one-shot reaction clips that must restart on every trigger.
        """
        _refuse_if_destroyed(self, "play")
        name = as_payload(clip)
        loops = as_payload(loops)
        next_clip = as_payload(next)
        min_hold = as_payload(min_hold)
        from .validate import expect_bool
        resume = expect_bool(resume, "play(resume=)")
        if not isinstance(name, str) or not name:
            raise TypeError(
                "play() expected a clip name string. Write sprite.play(\"walk\")."
            )
        if loops is not None:
            if isinstance(loops, bool) or not isinstance(loops, int) or loops < 1:
                raise ValueError(
                    f"play(loops=) must be a positive int, or omit to loop forever; got {loops!r}."
                )
        if next_clip is not None:
            if not isinstance(next_clip, str) or not next_clip:
                raise TypeError(
                    "play(next=) is a clip name string. "
                    "Write play(\"hit\", loops=1, next=\"idle\")."
                )
            self._sheet._require_cycle(next_clip)
        hold = 0.0 if min_hold is None else _positive_number(
            min_hold, what="play(min_hold=)", exclusive=False,
        )
        frames, fps, yoyo = self._sheet._require_cycle(name)
        if self._play_name is not None and self._play_loops is not None:
            # Settle an ended one-shot now: it was settled only by a draw, so a
            # hidden or culled sprite could not play it again (PB4).
            self._current_frame_index()
        if not (self._play_name == name and self._play_loops == loops
                and self._play_next == next_clip):
            # A linked size refuses before the clip switches, and before a
            # next= clip would raise from the frame loop (PB1).
            self._gate_clip_size(frames, "play")
            if next_clip is not None:
                self._gate_clip_size(self._sheet._require_cycle(next_clip)[0], "play(next=)")
        if (
            self._play_name == name
            and self._play_loops == loops
            and self._play_next == next_clip
        ):
            self._play_min_hold = hold
            return self
        if self._play_name is not None and self._play_min_hold > 0.0:
            elapsed = self._play_elapsed()
            # Due by ``reached`` (PM8 tolerance), not a bare ``<``: 0.25 s held
            # 16 frames at 1/60 for most start frames (review 2026-10-09 S7-2).
            if not reached(elapsed, self._play_min_hold):
                return self
        if self._play_name:
            self._play_resume_cache[self._play_name] = self._play_elapsed()
        start_elapsed = 0.0
        if resume:
            start_elapsed = float(self._play_resume_cache.get(name, 0.0))
        self._adopt_clip(
            name, frames, fps, yoyo,
            loops=loops, next=next_clip, start_elapsed=start_elapsed,
        )
        self._play_min_hold = hold
        self._warm_frame_fx_for_visual()
        return self

    def prepare_fx(self, *looks) -> "Sprite":
        """Warm FrameFx for listed looks (or the current visual if no args).

        Does not assign ``.visual``. ``prepare_fx(Halo, Aura)`` bakes the union
        (SDF implies path) for every sheet cell. ``prepare_fx()`` with no args
        warms only if the current costume needs a path/SDF; otherwise no-op.
        ``prepare_fx(Glow)`` is a no-op. Interned — destroy + recreate of the
        same PNG reuses the cache.
        """
        if not looks:
            self._warm_frame_fx_for_visual()
            return self
        need_path = False
        need_sdf = False
        for look in looks:
            path_n, sdf_n = _frame_fx_needs(look)
            need_path = need_path or path_n
            need_sdf = need_sdf or sdf_n
        if need_path or need_sdf:
            self._warm_frame_fx(sdf=need_sdf, all_cells=True)
        return self

    def _frame_fx_warm_indices(self) -> Tuple[int, ...]:
        """Frame indices to warm at assign time (clip or current cell)."""
        play = getattr(self, "_play_frames", None) or ()
        if play:
            return tuple(dict.fromkeys(int(i) for i in play))
        return (int(getattr(self, "_frame", 0) or 0),)

    def _warm_frame_fx_for_visual(self) -> None:
        """Bake FrameFx for the current ``.visual`` if it needs path/SDF."""
        vis = getattr(self, "_visual", None)
        path_n, sdf_n = _frame_fx_needs(vis)
        if not path_n and not sdf_n:
            return
        key = (id(vis), bool(sdf_n))
        if getattr(self, "_frame_fx_warm_key", None) == key:
            return
        self._warm_frame_fx(sdf=sdf_n)
        self._frame_fx_warm_key = key

    def _warm_shield_envelope_for_visual(self) -> None:
        """Bake the Shield costume envelope when the current look needs it."""
        if not _uses_shield_envelope(self):
            self._invalidate_shield_envelope()
            return
        self._ensure_shield_envelope()

    def _invalidate_shield_envelope(self) -> None:
        self._shield_env = None
        self._shield_env_key = None

    def _shield_env_cache_key(self) -> tuple:
        """Identity of the envelope bake (sheet + design units per pixel; not playhead).

        Every input of the bake: the scale per axis, not the size intent (PB10:
        a height-sized sprite stretched with ``width *= 2`` kept a stale
        envelope), and the sheet's pivot layout."""
        sheet = self._sheet
        n = int(getattr(sheet, "_nframes", 0) or 0)
        token = getattr(sheet, "_cache_token", id(sheet))
        kx, ky = self._du_per_px()
        return (token, n, getattr(sheet, "_layout_epoch", 0), round(kx, 6), round(ky, 6))

    def _frame_design_wh(self, fr) -> Tuple[float, float]:
        """Design-unit (w, h) for ``fr`` at this sprite's scale (scale=1)."""
        kx, ky = self._du_per_px()
        return float(fr.src_w) * kx, float(fr.src_h) * ky

    def _ensure_shield_envelope(self) -> Tuple[float, float, float, float]:
        """Union of per-frame alpha AABBs in design units (pivot origin, scale=1).

        Reuses ``auto_collider_for_frame(..., force_kind=\"bbox\")`` / ``_AUTO_CACHE``.
        Does not touch hitbox state. Empty masks are skipped; all-empty falls back
        to the current design box centered on the pivot.
        """
        key = self._shield_env_cache_key()
        env = getattr(self, "_shield_env", None)
        if env is not None and getattr(self, "_shield_env_key", None) == key:
            return env

        sheet = self._sheet
        n = int(getattr(sheet, "_nframes", 0) or 0)
        minx = miny = 1e300
        maxx = maxy = -1e300
        found = False
        for i in range(max(1, n)):
            fr = sheet._frame_at(i)
            img = sheet._image_for_frame(i)
            col = auto_collider_for_frame(img, fr, force_kind="bbox")
            if not col or not col.boxes:
                continue
            locals_b = boxes_to_local(col.boxes, fr)
            if not locals_b:
                continue
            du_w, du_h = self._frame_design_wh(fr)
            du_w = max(abs(float(du_w)), 1e-6)
            du_h = max(abs(float(du_h)), 1e-6)
            for nx, ny, nw, nh in locals_b:
                cx = float(nx) * du_w
                cy = float(ny) * du_h
                hw = abs(float(nw)) * du_w * 0.5
                hh = abs(float(nh)) * du_h * 0.5
                minx = min(minx, cx - hw)
                maxx = max(maxx, cx + hw)
                miny = min(miny, cy - hh)
                maxy = max(maxy, cy + hh)
                found = True

        if not found:
            w, h = abs(float(self.width)), abs(float(self.height))
            env = (0.0, 0.0, max(w, 1.0), max(h, 1.0))
        else:
            env = (
                0.5 * (minx + maxx),
                0.5 * (miny + maxy),
                max(maxx - minx, 1.0),
                max(maxy - miny, 1.0),
            )
        self._shield_env = env
        self._shield_env_key = key
        return env

    def _shield_envelope_frame(self) -> Tuple[float, float, float, float, float]:
        """World ``(cx, cy, w, h, ang_deg)`` of the Shield oval (includes ``shield_scale``).

        Center and angle follow the paint pose: flip, tilt about the baked
        ``hitbox_anchor``, normal-only seat, then heading. Width and height
        stay the frozen envelope. ``tilt == 0`` and no seat match the
        heading-only frame. Does not change the collider.
        """
        lx, ly, ew, eh = self._ensure_shield_envelope()
        s = abs(float(self._scale))
        sc = _sprite_ellipse_scale(self)
        w = max(abs(float(ew)) * s * sc, 1.0)
        h = max(abs(float(eh)) * s * sc, 1.0)
        ox, oy = self._apply_local_flip(float(self._offset_x), float(self._offset_y))
        elx, ely = self._apply_local_flip(float(lx) * s, float(ly) * s)
        cx, cy = get_xy(self.center, bare=True)
        tx, ty = ox + elx, oy + ely
        tilt = self._tilt_angle_for_paint()
        if abs(tilt) > 1e-12:
            px, py = self._tilt_pivot_local()
            dx, dy = tx - px, ty - py
            rad = math.radians(tilt)
            c = math.cos(rad)
            sn = math.sin(rad)
            tx = px + c * dx - sn * dy
            ty = py + sn * dx + c * dy
        sx, sy = self._tilt_seat_local(cx, cy)
        if abs(sx) > 1e-12 or abs(sy) > 1e-12:
            tx += sx
            ty += sy
        ang = self._draw_angle()
        if ang:
            rad = math.radians(ang)
            c = math.cos(rad)
            sn = math.sin(rad)
            cx += tx * c - ty * sn
            cy += tx * sn + ty * c
        else:
            cx += tx
            cy += ty
        if abs(tilt) > 1e-12:
            ang += tilt
        return cx, cy, w, h, ang

    def _shield_envelope_half(self) -> float:
        """Characteristic radius for Shield ProceduralFill UV mapping."""
        _lx, _ly, ew, eh = self._ensure_shield_envelope()
        s = abs(float(self._scale))
        sc = _sprite_ellipse_scale(self)
        return 0.5 * max(abs(float(ew)), abs(float(eh))) * s * sc

    def _warm_frame_fx(self, *, sdf: bool = False, all_cells: bool = False) -> None:
        """Bake FrameFx for sheet cells (interned).

        Assign-time warms the active clip or current cell. ``prepare_fx``
        passes ``all_cells=True`` to bake every cell. Other cells stay lazy
        until the first draw, including a grid sheet that is not an atlas.
        """
        from .atlas import frame_fx_for_frame
        sheet = getattr(self, "_sheet", None)
        if sheet is None:
            return
        n = int(getattr(sheet, "_nframes", 0) or 0)
        if n <= 0:
            n = int(getattr(sheet, "nframes", 0) or 0)
        if n <= 0:
            return
        if all_cells:
            indices = range(n)
        else:
            indices = self._frame_fx_warm_indices()
        for idx in indices:
            fr = sheet._frame_at(idx)
            img = sheet._image_for_frame(idx)
            frame_fx_for_frame(img, fr, sdf=bool(sdf))

    def _clone_pose_from(self, source) -> None:
        """Rotation / scale / flips (``Graphic``), and ``tilt`` in whichever form it holds."""
        super()._clone_pose_from(source)
        # A contact lean sticks until overwritten, so it is state like the rest.
        for name in ("_tilt", "_tilt_mode", "_tilt_contact_point", "_tilt_contact_angle",
                     "_tilt_contact_normal", "_tilt_contact_side"):
            if hasattr(source, name):
                setattr(self, name, getattr(source, name))

    def _clone_recipe(self, *, center=None, frame=None, **kwargs) -> "Sprite":
        """Construct via the normal Sprite constructor with this sheet (shared)."""
        if center is None:
            center = get_xy(self.center, bare=True)
        fr = self.frame if frame is None else frame
        cell = self._sheet._frame_at(self._sheet.frame_index(fr))
        return self._copy_main_hitbox_switch(type(self)(
            self._sheet,
            frame=fr,
            hitbox_shape=self._hitbox_kind,
            hitbox_source=self._hitbox_from,
            hitbox_anchor=self._hitbox_anchor,
            hitbox_scale=self._hitbox_scale,
            shield_scale=self._shield_scale,
            offset=self.offset,
            flip_x=self._flip_x,
            flip_y=self._flip_y,
            art_angle=self._art_angle,
            center=center,
            **self._size_intent_kwargs(cell),
            **kwargs,
        ))

    def _copy_main_hitbox_switch(self, copy):
        """A clone collides like its source: ``hitbox.active = False`` is a
        main-hitbox knob like its shape and scale (review 2026-10-09 S7-8)."""
        if self.__dict__.get("_main_hitbox_off", False):
            copy.hitbox.active = False
        return copy

    def _adopt_clip(
        self,
        name: str,
        frames: Sequence[int],
        fps: float,
        yoyo: bool,
        *,
        loops: Optional[int] = None,
        next: Optional[str] = None,
        start_elapsed: float = 0.0,
        engine: bool = False,
    ) -> None:
        self._play_name = name
        self._play_frames = tuple(frames)
        self._play_fps = float(fps)
        self._play_yoyo = bool(yoyo)
        self._play_loops = loops
        self._play_next = next
        scale = float(self._time_scale) if float(self._time_scale) else 1.0
        self._play_t0 = _world_time() - max(0.0, float(start_elapsed)) / scale
        # While frozen (time_scale 0) the new clip shows its own start, not the
        # old clip's frozen phase (PB5).
        self._play_frozen_elapsed = max(0.0, float(start_elapsed))
        if self._play_frames:
            self._frame = self._play_frames[0]
            self._apply_size_intent(self._sheet._frame_at(self._frame),
                                    keep_linked=engine)
        # A clip that ends ends in the simulation (``settle_clip_ends``), not
        # in whatever reads the frame first.
        _schedule_clip_end(self)
        self._sync_clip_hitbox()

    def _size_intent_kwargs(self, fr=None) -> dict:
        """Constructor knobs that rebuild this sprite's scale on cell ``fr``.

        The kwarg kind follows the size intent (``size`` / ``width`` /
        ``height`` / both); the value is ``fr`` at ``_du_per_px``, so a clone
        made mid-clip keeps the scale. Both ``width`` and ``height`` parse as
        stretch (per-axis scale).
        """
        if fr is None:
            fr = self._current_cell()
        w, h = self._frame_design_wh(fr)
        intent = getattr(self, "_size_intent", "default")
        if intent == "size":
            return {"size": max(w, h)}
        if intent == "width":
            return {"width": w}
        if intent == "height":
            return {"height": h}
        return {"width": w, "height": h}

    def _play_elapsed(self) -> float:
        """Seconds the current clip has been advancing (respects ``time_scale``)."""
        if not self._play_frames:
            return 0.0
        scale = float(self._time_scale)
        if scale == 0.0:
            return float(self._play_frozen_elapsed)
        return max(0.0, (_world_time() - self._play_t0) * scale)

    @property
    def time_scale(self) -> float:
        """Multiplier on this sprite's clip clock. ``0`` freezes the playhead."""
        return self._time_scale

    @time_scale.setter
    def time_scale(self, value) -> None:
        from .entity import _time_scale_value
        new = _time_scale_value(self, value)
        elapsed = self._play_elapsed()
        if new == 0.0:
            self._play_frozen_elapsed = elapsed
        elif self._play_frames:
            self._play_t0 = _world_time() - elapsed / new
        self._time_scale = new
        if self._play_frames and self._play_loops is not None:
            _schedule_clip_end(self)     # the end moved with the scale

    def _du_per_px(self) -> Tuple[float, float]:
        """Design units per source pixel — one scale for every cell (scale=1).

        Set by the size asked at construction (``height=`` / ``width=`` /
        ``size=`` against the construct cell's PNG, or atlas ``sourceSize``).
        Derived from the live ``width`` / ``height`` and the cell they were
        fitted to, so an author write to ``width`` / ``height`` / ``size``
        rescales every clip with no extra bookkeeping. Stretch (both given)
        keeps a per-axis scale.
        """
        rw = float(getattr(self, "_ref_src_w", 0.0) or 0.0)
        rh = float(getattr(self, "_ref_src_h", 0.0) or 0.0)
        kx = abs(float(self.width)) / rw if rw else 1.0
        ky = abs(float(self.height)) / rh if rh else 1.0
        return kx, ky

    def _gate_clip_size(self, frames, operation: str) -> None:
        """Refuse a clip whose first cell would rewrite a linked ``width`` /
        ``height`` (``_apply_size_intent``), before anything changes."""
        if not frames:
            return
        fr = self._sheet._frame_at(frames[0])
        kx, ky = self._du_per_px()
        if (abs(float(self.width) - float(fr.src_w) * kx) <= 1e-9
                and abs(float(self.height) - float(fr.src_h) * ky) <= 1e-9):
            return
        from .shapes import _ensure_writable
        _ensure_writable(self["width"], operation)
        _ensure_writable(self["height"], operation)

    def _apply_size_intent(self, fr, *, keep_linked: bool = False) -> None:
        """Move ``width`` / ``height`` to ``fr`` at the sprite's one scale.

        Each cell draws at its own PNG size times ``_du_per_px``: a pack
        cropped per animation (a short slide, a wide fall) keeps its
        proportions. Called on ``play()`` / ``frame=``, not on playhead ticks.
        """
        kx, ky = self._du_per_px()
        px_w, px_h = float(fr.src_w), float(fr.src_h)
        du_w, du_h = px_w * kx, px_h * ky
        if abs(float(self.width) - du_w) > 1e-9 or abs(float(self.height) - du_h) > 1e-9:
            if keep_linked and self._size_is_linked():
                # An engine switch (``next=``) has no call site to refuse at:
                # the link owns the size (review 2026-10-09 S7-7).
                return
            self.width = du_w
            self.height = du_h
        self._ref_src_w = px_w
        self._ref_src_h = px_h

    def _size_is_linked(self) -> bool:
        from .shapes import _ensure_writable
        from .state import LinkedAttributeError
        try:
            _ensure_writable(self["width"], "play")
            _ensure_writable(self["height"], "play")
        except LinkedAttributeError:
            return True
        return False

    def _current_frame_index(self) -> int:
        seq = self._play_frames
        if not seq or self._play_fps <= 0.0:
            return self._frame
        elapsed = self._play_elapsed()
        # ``process.whole_steps`` inlined (this runs per sprite per draw): the
        # frame count with the PM8 tolerance (PB3: int() was a frame late).
        x = elapsed * self._play_fps
        idx = int(x)
        if x >= idx + 1 - _DUE_EPS * (idx + 1 if idx else 1):
            idx += 1
        n = len(seq)
        yoyo = self._play_yoyo
        loops = self._play_loops
        if loops is None:
            return seq[_clip_step(idx, n, yoyo)]
        total = _clip_period(n, yoyo) * loops
        if idx >= total:
            if getattr(self, "_destroyed", False):
                return seq[-1]                    # a read on a dead sprite changes nothing (PB4)
            next_clip = self._play_next
            if next_clip:
                # Switch without going through play() idempotence (t0 must reset).
                if self._play_name:
                    self._play_resume_cache[self._play_name] = elapsed
                frames, fps, yoyo = self._sheet._require_cycle(next_clip)
                # The next clip starts at the boundary, not at this read (PB4):
                # carry the time already spent past the end.
                overshoot = max(0.0, elapsed - total / self._play_fps)
                self._adopt_clip(next_clip, frames, fps, yoyo, start_elapsed=overshoot,
                                 engine=True)
                self._play_min_hold = 0.0
                return self._current_frame_index() if self._play_frames else self._frame
            hold = seq[0] if yoyo else seq[-1]
            self._frame = hold
            self._play_name = None
            self._play_frames = ()
            self._play_due = None
            self._sync_clip_hitbox()
            return hold
        return seq[_clip_step(idx, n, yoyo)]

    # --- pose / collision / draw ---------------------------------------------

    def _flipped_art_angle(self) -> float:
        """Bitmap nose in degrees after ``flip_*`` reflection."""
        return _flipped_art_angle(
            self._art_angle,
            flip_x=self._flip_x,
            flip_y=self._flip_y,
        )

    def _draw_angle(self) -> float:
        """Collider / hit-test degrees: world heading minus the flipped bitmap nose."""
        return float(self._rotation) - self._flipped_art_angle()

    def _paint_angle(self) -> float:
        """Drawn-cell degrees: ``_draw_angle`` plus visual-only ``tilt``."""
        return self._draw_angle() + self._tilt_angle_for_paint()

    def _tilt_angle_for_paint(self) -> float:
        mode = getattr(self, "_tilt_mode", "angle")
        if mode == "angle":
            return float(self._tilt)
        if mode == "contact":
            return float(getattr(self, "_tilt_contact_angle", 0.0))
        c = self._select_ground_contact()
        return float(c.slope_angle) if c is not None else 0.0

    def _select_ground_contact(self):
        """Pick one deterministic bottom contact for auto tilt."""
        contacts = getattr(self, "_touching_contacts", ()) or ()
        bottom = []
        for c in contacts:
            if c.side != "bottom":
                continue
            # Prefer contacts with a point for tie-breaks.
            if c.point is not None:
                px, py = c.point
            else:
                px, py = 0.0, -1e300
            bottom.append((float(py), float(px), float(c.slope_angle), c))

        if not bottom:
            return None

        # Highest point.y wins; if tied, prefer the more tilted candidate.
        bottom.sort(
            key=lambda t: (-t[0], -abs(t[2]), t[1], id(t[3])),
        )
        return bottom[0][3]

    def _design_box_anchor_local(self) -> Tuple[float, float]:
        """Anchor on the PNG design box, post-flip. Used when no hitbox is baked."""
        w, h = self._pose_source_wh()
        w, h = abs(float(w)), abs(float(h))
        px, py = self._current_pivot()
        lx = (0.5 - px) * w + self._offset_x
        ly = (py - 0.5) * h + self._offset_y
        ax, ay = _anchor_on_aabb(
            -0.5 * w, -0.5 * h, 0.5 * w, 0.5 * h, self._hitbox_anchor,
        )
        return self._apply_local_flip(lx + ax, ly + ay)

    def _tilt_pivot_local(self) -> Tuple[float, float]:
        """Offset from ``center`` to the tilt pivot (unrotated, y-up, post-flip).

        The pivot is the baked ``hitbox_anchor`` (after pin and ``hitbox_scale``),
        mapped through ``_hitbox_pose_wh`` — the same box the collider uses.
        Paint flips the cell first (innermost ``scale(fx, -fy)``) and tilts
        after, so the pivot is the anchor **as drawn**: mirrored under
        ``flip_x`` / ``flip_y``, the same point the emitted collider uses.
        With no bake yet, the same anchor on the design box.
        """
        aabb = self._local_prims_aabb()
        if aabb is None:
            return self._design_box_anchor_local()
        w, h = self._hitbox_pose_wh()
        w, h = abs(float(w)), abs(float(h))
        ax, ay = _anchor_on_aabb(*aabb, self._hitbox_anchor)
        # Draw shifts the cell by ``offset``; the feet the seat drops onto
        # the contact are that shifted point, not the un-offset anchor.
        return self._apply_local_flip(
            ax * w + float(self._offset_x), ay * h + float(self._offset_y),
        )

    def _anchor_is_bottom_face(self) -> bool:
        """True when ``hitbox_anchor`` is the bottom-centre of the hitbox."""
        ax, ay = _anchor_pair(self._hitbox_anchor)
        return abs(ax) <= 1e-3 and abs(ay + 1.0) <= 1e-3

    def _tilt_seat_contact(self):
        """``(point, normal)`` for a bottom contact that may seat the feet.

        A bare angle has no plane. ``"center"`` / ``"top"`` / side anchors are
        not dropped onto the floor. ``"ground"`` reads the live bottom contact;
        a stored ``TouchingContact`` seats only while its ``side`` is ``"bottom"``.
        """
        mode = getattr(self, "_tilt_mode", "angle")
        if mode == "angle":
            return None
        if not self._anchor_is_bottom_face():
            return None
        if mode == "contact":
            if getattr(self, "_tilt_contact_side", None) != "bottom":
                return None
            return (
                getattr(self, "_tilt_contact_point", None),
                getattr(self, "_tilt_contact_normal", None),
            )
        c = self._select_ground_contact()
        if c is None:
            return None
        return c.point, c.normal

    def _tilt_seat_local(self, cx: float, cy: float) -> Tuple[float, float]:
        """Post-heading shift that puts the baked bottom anchor on the contact plane.

        Motion is along ``contact.normal`` only (no slide toward a toe or corner).
        ``(0, 0)`` on flat ground, in the air, for a bare angle, and for any
        anchor that is not the bottom face. Does not move ``center``.
        """
        plane = self._tilt_seat_contact()
        if plane is None:
            return 0.0, 0.0
        point, normal = plane
        if point is None or normal is None:
            return 0.0, 0.0
        try:
            sx, sy = float(point[0]), float(point[1])
        except Exception:
            try:
                sx, sy = float(point.x), float(point.y)
            except Exception:
                return 0.0, 0.0
        try:
            nx, ny = float(normal[0]), float(normal[1])
        except Exception:
            try:
                nx, ny = float(normal.x), float(normal.y)
            except Exception:
                return 0.0, 0.0
        nlen2 = nx * nx + ny * ny
        if nlen2 < 1e-12:
            return 0.0, 0.0
        px, py = self._tilt_pivot_local()
        draw_ang = self._draw_angle()
        rad = math.radians(draw_ang) if abs(draw_ang) > 1e-12 else 0.0
        c = math.cos(rad)
        s = math.sin(rad)
        ax = float(cx) + c * px - s * py
        ay = float(cy) + s * px + c * py
        # anchor + t * normal lies on the plane through the contact point.
        t = -((ax - sx) * nx + (ay - sy) * ny) / nlen2
        if abs(t) < 1e-9:
            return 0.0, 0.0
        wx, wy = t * nx, t * ny
        # Shift is applied after heading, so convert the world move back.
        return c * wx + s * wy, -s * wx + c * wy

    def _apply_paint_xform(
        self, skia_canvas: skia.Canvas, cx: float, cy: float, fx: float, fy: float,
    ) -> None:
        """Translate to center, apply heading + tilt, then flip.

        Callers must ``save``/``restore`` around this. Tilt rotates about the
        baked ``hitbox_anchor``. When that anchor is the bottom face and the
        lean comes from a bottom contact, the paint also shifts along the
        contact normal so the anchor meets the ramp. ``center`` and the
        collider stay put. ``_draw_angle`` still rotates about ``center``.
        """
        draw_ang = self._draw_angle()
        tilt = self._tilt_angle_for_paint()
        sx, sy = self._tilt_seat_local(cx, cy)

        skia_canvas.translate(cx, cy)
        if draw_ang:
            skia_canvas.rotate(draw_ang)
        if abs(sx) > 1e-12 or abs(sy) > 1e-12:
            skia_canvas.translate(sx, sy)
        if abs(tilt) > 1e-12:
            px, py = self._tilt_pivot_local()
            skia_canvas.translate(px, py)
            skia_canvas.rotate(tilt)
            skia_canvas.translate(-px, -py)
        skia_canvas.scale(fx, -fy)

    def _current_pivot(self) -> Tuple[float, float]:
        fr = self._sheet._frame_at(self._current_frame_index())
        return float(fr.pivot_x), float(fr.pivot_y)

    def _current_cell(self):
        """Atlas frame for the playhead (does not write ``_frame``)."""
        idx = self._current_frame_index() if self._play_frames else int(self._frame)
        return self._sheet._frame_at(idx)

    def _pixel_scale(self, fr=None) -> Tuple[float, float]:
        """Design units per source pixel for the blit (``_du_per_px`` × ``scale``).

        The same for every cell: each draws at its own ``sourceSize``. ``fr``
        is accepted for call-site symmetry and ignored.
        """
        s = abs(float(self._scale))
        kx, ky = self._du_per_px()
        return kx * s, ky * s

    def _pose_source_wh(self) -> Tuple[float, float]:
        """World size of the *drawn* design box (current cell after ``play()``)."""
        s = abs(float(self._scale))
        return abs(float(self.width)) * s, abs(float(self.height)) * s

    def _collision_pose_anchor(self) -> Tuple[float, float]:
        """Snapshot-cache translation anchor: the pose point ``center``.

        Baked colliders are placed about ``center`` (the pivot). The inherited
        ``Graphic._center_xy`` is the *drawn* box centre, which moves when a
        cell of another size or pivot plays (a slide under ``anchor="bottom"``,
        an authored atlas pivot, ``clip(offset=)``). Keyed on that, the cache's
        translate fast path slid the unchanged body by the visual shift — a
        resting walker floated or sank when its clip changed.
        """
        return get_xy(self.center, bare=True)

    def _collision_pose_extra(self) -> Tuple[float, ...]:
        """Non-translational pose for the snapshot cache (hitbox box + heading)."""
        w, h = self._hitbox_pose_wh()
        return (
            float(self._draw_angle()),
            float(self._scale),
            float(self._hitbox_scale[0]),
            float(self._hitbox_scale[1]),
            float(w),
            float(h),
            1.0 if self._flip_x else 0.0,
            1.0 if self._flip_y else 0.0,
            float(self._offset_x),
            float(self._offset_y),
        )

    def _visual_local_center(self, w: float, h: float) -> Tuple[float, float]:
        """Offset from ``center`` (the pivot) to the visual-rect centre, unrotated."""
        px, py = self._current_pivot()
        lx = (0.5 - px) * w + self._offset_x
        ly = (py - 0.5) * h + self._offset_y
        return self._apply_local_flip(lx, ly)

    def _draw_aabb(self) -> Optional[Tuple[float, float, float, float]]:
        """World AABB of what ``_blit_image`` draws this frame: the cell on
        show (its own size, trim and pivot), ``offset``, flips, heading, tilt
        and seat, mapped through the paint transform (``_apply_paint_xform``).
        None when nothing is drawn. The cull and the filter-batch bounds read
        it (``canvas._approx_draw_aabb``): a clip whose cells differ in size
        drew past a box sized at ``play()``.
        """
        loc = self._blit_local_dst()
        if loc is None:
            return None
        cx, cy, _ang, fx, fy, dst, _fr, _idx = loc
        # The paint transform, applied to the corners in float64 (a skia Rect
        # is float32): translate · heading · seat · tilt about its pivot · flip.
        draw_ang = self._draw_angle()
        sx, sy = self._tilt_seat_local(cx, cy)
        tilt = self._tilt_angle_for_paint()
        if abs(tilt) > 1e-12:
            px, py = self._tilt_pivot_local()
            rt = math.radians(tilt)
            ct, st_ = math.cos(rt), math.sin(rt)
        if draw_ang:
            ra = math.radians(draw_ang)
            ca, sa = math.cos(ra), math.sin(ra)
        l, t, r, b = float(dst.left()), float(dst.top()), float(dst.right()), float(dst.bottom())
        vis = probe_private(self, "_visual", None)
        if vis is not None and getattr(vis, "_needs_sprite_sdf", False):
            # SDF bands paint one quad, the cell padded by the SDF border
            # (``_draw_sprite_sdf_bands``): its size follows the cell, no bake.
            px_l, px_t = _sdf_quad_pad(_fr, r - l, b - t)
            l, t, r, b = l - px_l, t - px_t, r + px_l, b + px_t
        xs = []
        ys = []
        for x, y in ((l, t), (r, t), (r, b), (l, b)):
            x, y = fx * x, -fy * y
            if abs(tilt) > 1e-12:
                x, y = x - px, y - py
                x, y = x * ct - y * st_ + px, x * st_ + y * ct + py
            x, y = x + sx, y + sy
            if draw_ang:
                x, y = x * ca - y * sa, x * sa + y * ca
            xs.append(x + cx)
            ys.append(y + cy)
        return (min(xs), min(ys), max(xs), max(ys))

    def _oriented_frame(self) -> Tuple[float, float, float, float, float]:
        """``(cx, cy, w, h, ang_deg)`` of the drawn sprite (scale + pivot applied)."""
        cx, cy = get_xy(self.center, bare=True)
        w, h = self._pose_source_wh()
        w, h = abs(float(w)), abs(float(h))
        lx, ly = self._visual_local_center(w, h)
        ang = self._draw_angle()
        if ang:
            rad = math.radians(ang)
            c = math.cos(rad)
            sn = math.sin(rad)
            cx += lx * c - ly * sn
            cy += lx * sn + ly * c
        else:
            cx += lx
            cy += ly
        return cx, cy, w, h, ang

    @property
    def art_box(self):
        """A Box around the opaque pixels of the cell on screen (the art itself).

        ``sprite.box`` is the whole cell, transparent padding included;
        ``sprite.hitbox.box`` is the collider. ``art_box`` is where the
        drawing visibly is — it follows the animation (a run cycle's feet
        move it). Placed like the drawing: pivot, ``offset``, flips, ``scale``,
        heading. A fully transparent cell answers ``sprite.box``.
        """
        from .box import Box, region_name_signs
        idx = self._current_frame_index() if self._play_frames else int(self._frame)
        sheet = self._sheet
        fr = sheet._frame_at(idx)
        col = auto_collider_for_frame(sheet._image_for_frame(idx), fr, force_kind="bbox")
        locals_b = boxes_to_local(col.boxes, fr) if col and col.boxes else ()
        if not locals_b:
            return self.box
        s = abs(float(self._scale))
        du_w, du_h = self._frame_design_wh(fr)
        du_w, du_h = abs(float(du_w)) * s, abs(float(du_h)) * s
        minx = min((nx - abs(nw) * 0.5) * du_w for nx, _ny, nw, _nh in locals_b)
        maxx = max((nx + abs(nw) * 0.5) * du_w for nx, _ny, nw, _nh in locals_b)
        miny = min((ny - abs(nh) * 0.5) * du_h for _nx, ny, _nw, nh in locals_b)
        maxy = max((ny + abs(nh) * 0.5) * du_h for _nx, ny, _nw, nh in locals_b)
        lx = 0.5 * (minx + maxx) + float(self._offset_x)
        ly = 0.5 * (miny + maxy) + float(self._offset_y)
        lx, ly = self._apply_local_flip(lx, ly)
        cx, cy = get_xy(self.center, bare=True)
        ang = self._draw_angle()
        if ang:
            rad = math.radians(ang)
            c, sn = math.cos(rad), math.sin(rad)
            cx, cy = cx + lx * c - ly * sn, cy + lx * sn + ly * c
        else:
            cx, cy = cx + lx, cy + ly
        # Heading as the angle (as ``.box``): same region, and its names.
        heading = self._rotation_value()
        return Box._snapshot(
            cx, cy, maxx - minx, maxy - miny, heading,
            name_signs=region_name_signs(self),
        )

    @property
    def is_collapsed(self) -> bool:
        """True when drawn frame has no interior (width or height ``0``, incl. scale)."""
        if float(self._scale) == 0.0:
            return True
        _cx, _cy, w, h, _ang = self._oriented_frame()
        return w == 0.0 or h == 0.0

    def _collision_frame(self) -> Tuple[float, float, float, float, float]:
        cx, cy, w, h, ang = self._oriented_frame()
        w, h = abs(float(w)), abs(float(h))
        sx, sy = self._hitbox_scale
        ax, ay = _anchor_on_aabb(-0.5 * w, -0.5 * h, 0.5 * w, 0.5 * h, self._hitbox_anchor)
        ncx, ncy = _scale_about(0.0, 0.0, ax, ay, sx, sy)
        nw, nh = w * sx, h * sy
        rad = math.radians(float(ang))
        c = math.cos(rad)
        sn = math.sin(rad)
        cx += ncx * c - ncy * sn
        cy += ncx * sn + ncy * c
        return cx, cy, nw, nh, ang

    def _collision_specs(self) -> List[Tuple]:
        """World-space prims for ``snapshot_shape`` (baked local boxes × pose)."""
        self._ensure_auto_baked()
        kind = self._hitbox_kind
        ang_deg = self._draw_angle()
        ang = math.radians(ang_deg)
        if (
            self._hitbox_circle is not None
            or self._hitbox_circles
            or self._hitbox_ellipse is not None
            or self._hitbox_ellipses
            or self._hitbox_poly
            or self._hitbox_boxes
        ):
            w, h = self._hitbox_pose_wh()
            w, h = abs(float(w)), abs(float(h))
            pcx, pcy = get_xy(self.center, bare=True)
            ox, oy = self._apply_local_flip(
                float(self._offset_x), float(self._offset_y),
            )
            c = math.cos(ang)
            sn = math.sin(ang)
            pcx += ox * c - oy * sn
            pcy += ox * sn + oy * c
            out = _emit_baked_specs(self, self, pcx, pcy, ang, w, h)
            if out:
                return out
        # Empty bake: same scale and anchor as the proxy, not the raw blit rect.
        cx, cy, w, h, _ang = self._collision_frame()
        w, h = abs(float(w)), abs(float(h))
        if kind == "ellipse":
            rx, ry = w * 0.5, h * 0.5
            r_circ = ellipse_as_circle(rx, ry)
            if r_circ is not None:
                return [("circle", cx, cy, r_circ)]
            return [("ellipse", cx, cy, rx, ry, ang)]
        if kind == "circle":
            return [("circle", cx, cy, min(w, h) * 0.5)]
        hw, hh = w * 0.5, h * 0.5
        if abs(ang) < 1e-6 or abs(abs(ang) - math.pi) < 1e-6:
            return [("aabb", cx - hw, cy - hh, cx + hw, cy + hh)]
        return [("obb", cx, cy, hw, hh, ang)]

    def _parts_written_by_drag(self) -> Tuple[Container, ...]:
        return (self.center,)

    # wheel_rotate inherits Shape default: (self["angle"],) — CTM pose.

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> "Sprite":
        """Translate center. A1 bare-float when unlinked; batched takein when pull consumers exist."""
        if _pose_fast_ok(self, force=force):
            _translate_point_float(self.center, dx, dy)
            return self
        return self._move_by_batched(dx, dy, force=force)

    @batch_update_self()
    def _move_by_batched(self, dx: float, dy: float, *, force: bool = False) -> "Sprite":
        _ensure_writable(self.center, "move_by", force=force)
        cx = _bare_attr(self.center.x)
        cy = _bare_attr(self.center.y)
        if dx is not None:
            cx = cx + float(dx)
        if dy is not None:
            cy = cy + float(dy)
        self.center._takein((cx, cy))
        return self

    def _move_to_xy(self) -> Tuple[float, float]:
        """The point ``_move_to`` places (``center``); a sheet anchor puts the
        art frame, the turn and scale pivot, elsewhere. The timed ``move_to``
        measures its delta from here."""
        c = self.center
        return (_bare_attr(c.x), _bare_attr(c.y))

    def _move_to(self, x: float, y: float, *, force: bool = False) -> "Sprite":
        """Absolute center placement. Same A1 / pull-invalidate split as Circle/Rect."""
        if _pose_fast_ok(self, force=force):
            cx = _bare_attr(self.center.x)
            cy = _bare_attr(self.center.y)
            nx = cx if x is None else float(x)
            ny = cy if y is None else float(y)
            if nx != cx:
                _takein_xy_float(self.center, x=nx)
            if ny != cy:
                _takein_xy_float(self.center, y=ny)
            return self
        return self._move_to_batched(x, y, force=force)

    @batch_update_self()
    def _move_to_batched(self, x: float, y: float, *, force: bool = False) -> "Sprite":
        _ensure_writable(self.center, "move_to", force=force)
        cx = _bare_attr(self.center.x)
        cy = _bare_attr(self.center.y)
        nx = cx if x is None else float(x)
        ny = cy if y is None else float(y)
        if nx != cx or ny != cy:
            self.center._takein((nx, ny))
        return self

    def _hit_test_xy(self, x: float, y: float) -> bool:
        """Hit-test the painted cell: current-frame alpha, tilt included.

        A miss on the oriented visual rect stays a miss. A hit samples the
        current frame's display mask (same alpha floor as auto-hitbox), not
        the baked collider and not a glow or FrameFx outline.
        """
        _cx, _cy, w, h, _ang = self._oriented_frame()
        if w <= 0.0 or h <= 0.0:
            return False
        lx, ly = self._pointer_local(x, y)
        vcx, vcy = self._visual_local_center(w, h)
        if abs(lx - vcx) > w * 0.5 or abs(ly - vcy) > h * 0.5:
            return False
        return self._opaque_texel(lx, ly)

    def _pointer_local(self, x: float, y: float) -> Tuple[float, float]:
        """Design point → y-up local blit space: heading, tilt seat and tilt undone."""
        scx, scy = get_xy(self.center, bare=True)
        dx = x - scx
        dy = y - scy
        draw_ang = self._draw_angle()
        if draw_ang:
            rad = math.radians(-draw_ang)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            lx = dx * cos_a - dy * sin_a
            ly = dx * sin_a + dy * cos_a
        else:
            lx, ly = dx, dy
        seat_x, seat_y = self._tilt_seat_local(scx, scy)
        lx -= seat_x
        ly -= seat_y
        tilt = self._tilt_angle_for_paint()
        if abs(tilt) > 1e-12:
            px, py = self._tilt_pivot_local()
            lx -= px
            ly -= py
            rad = math.radians(-tilt)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            lx, ly = lx * cos_a - ly * sin_a, lx * sin_a + ly * cos_a
            lx += px
            ly += py
        return lx, ly

    def _opaque_texel(self, lx: float, ly: float) -> bool:
        """True when ``(lx, ly)`` lands on an opaque texel of the current cell.

        ``lx, ly`` are y-up after undoing heading, seat, and tilt — still in
        the space of the blit ``scale(flip_x, -flip_y)``. The mask is the
        current frame (packed atlas cells un-rotated like the blit), cached,
        max side 32, alpha at least the auto-hitbox floor.
        """
        fx = -1.0 if self._flip_x else 1.0
        fy = -1.0 if self._flip_y else 1.0
        local_x = lx / fx
        local_y = ly / (-fy)
        idx = self._current_frame_index() if self._play_frames else int(self._frame)
        sheet = self._sheet
        fr = sheet._frame_at(idx)
        image = sheet._image_for_frame(idx)
        if image is None:
            return False
        sx, sy = self._pixel_scale(fr)
        if sx <= 0.0 or sy <= 0.0:
            return False
        left = (float(fr.src_x) - float(fr.pivot_x) * float(fr.src_w)) * sx + self._offset_x
        top = (float(fr.src_y) - float(fr.pivot_y) * float(fr.src_h)) * sy - self._offset_y
        packed_w = float(fr.h if fr.rotated else fr.w)
        packed_h = float(fr.w if fr.rotated else fr.h)
        dw = packed_w * sx
        dh = packed_h * sy
        if dw <= 0.0 or dh <= 0.0:
            return False
        u = (local_x - left) / dw
        v = (local_y - top) / dh
        if u < 0.0 or v < 0.0 or u > 1.0 or v > 1.0:
            return False
        mask = _display_mask(image, fr)
        mh, mw = mask.shape
        if mw <= 0 or mh <= 0:
            return False
        col = min(mw - 1, int(u * mw))
        row = min(mh - 1, int(v * mh))
        return bool(mask[row, col])

    def _draw_sprite_ellipse(self, skia_canvas: skia.Canvas, paint) -> None:
        """Stroke/fill the costume ellipse (Electric* / Shield / Halo rims).

        Shield / plasma use the frozen silhouette-union envelope ×
        :attr:`shield_scale` (default 1.4). Electric* / Halo stay 1:1 with the
        frame and prefer the cached silhouette path when available (all
        qualities — survival keeps cheaper paints, not an ellipse stand-in).
        """
        if paint is None:
            return
        if _uses_shield_envelope(self):
            cx, cy, w, h, ang = self._shield_envelope_frame()
            if w <= 0.0 or h <= 0.0:
                return
            skia_canvas.save()
            skia_canvas.translate(cx, cy)
            if ang:
                skia_canvas.rotate(ang)
            hw, hh = 0.5 * w, 0.5 * h
            skia_canvas.drawOval(skia.Rect.MakeLTRB(-hw, -hh, hw, hh), paint)
            skia_canvas.restore()
            return
        scale = _sprite_ellipse_scale(self)
        if abs(scale - 1.0) < 1e-6:
            if self._draw_sprite_silhouette(skia_canvas, paint):
                return
        cx, cy, w, h, ang = self._oriented_frame()
        if w <= 0.0 or h <= 0.0:
            return
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        if ang:
            skia_canvas.rotate(ang)
        hw, hh = 0.5 * w * scale, 0.5 * h * scale
        skia_canvas.drawOval(skia.Rect.MakeLTRB(-hw, -hh, hw, hh), paint)
        skia_canvas.restore()

    def _rebuild_blit_paint(self) -> None:
        """Set-time blit Paint: shared singleton when default, else one cached Paint.

        Covers ``_blend``, ``_alpha``, static HueShift ``_blit_color_filter``
        and the Grayscale ``_blit_gray_cf`` (composed on top of hue).
        Live hue uses ``_blit_hue_sksl`` (applies extras there) and does not
        need a non-default ``_blit_paint``. Blend / alpha alone must not clear
        ``_plain_blit``.
        """
        blend = getattr(self, "_blend", BlendMode.NORMAL)
        alpha = float(getattr(self, "_alpha", 1.0))
        cf = getattr(self, "_blit_color_filter", None)
        gray = probe_private(self, "_blit_gray_cf", None)
        if blend is BlendMode.NORMAL and cf is None and gray is None and alpha >= 1.0:
            self._blit_paint = _BLIT_PAINT
            return
        p = skia.Paint(AntiAlias=True)
        if cf is not None:
            p.setColorFilter(cf)
        self._apply_blit_paint_extras(p)
        self._blit_paint = p

    def _apply_blit_paint_extras(self, paint) -> None:
        """Stamp gray, non-default blend / alpha onto a blit Paint (every body route)."""
        gray = probe_private(self, "_blit_gray_cf", None)
        if gray is not None:
            inner = paint.getColorFilter()
            paint.setColorFilter(
                gray if inner is None else skia.ColorFilters.Compose(gray, inner))
        if self._blend is not BlendMode.NORMAL:
            paint.setBlendMode(_SKIA_BLEND_MAP[self._blend])
        if self._alpha < 1.0:
            paint.setAlphaf(self._alpha)

    def _install_blit_color_filter(self, cf) -> None:
        """HueShift static ColorFilter on the blit paint (plain-blit safe)."""
        self._blit_color_filter = cf
        self._blit_hue_live = None
        self._rebuild_blit_paint()
        self._refresh_plain_blit()

    def _install_blit_hue_live(self, amount) -> None:
        """Live HueShift amount (SkSL each frame). Clears static ColorFilter."""
        self._blit_hue_live = None if amount is None else float(amount)
        if self._blit_hue_live is not None:
            self._blit_color_filter = None
        self._rebuild_blit_paint()
        self._refresh_plain_blit()

    def _install_blit_gray(self, cf) -> None:
        """Grayscale ColorFilter on every blit paint, on top of hue (plain-blit safe)."""
        self._blit_gray_cf = cf
        self._rebuild_blit_paint()
        self._refresh_plain_blit()

    def _refresh_plain_blit(self) -> None:
        """Static HueShift ColorFilter alone stays on the cheap blit path."""
        from .stamps import has_any_stamp
        vis = getattr(self, "_visual", None)
        if vis is not None:
            object.__setattr__(self, "_plain_blit", False)
            return
        if getattr(self, "_glow", None) is not None or getattr(self, "_shadow", None) is not None:
            object.__setattr__(self, "_plain_blit", False)
            return
        if getattr(self, "_tail", None) is not None:
            object.__setattr__(self, "_plain_blit", False)
            return
        if getattr(self, "_fill_filter", None) is not None or getattr(
            self, "_line_filter", None
        ) is not None:
            object.__setattr__(self, "_plain_blit", False)
            return
        if getattr(self, "_blit_hue_live", None) is not None:
            object.__setattr__(self, "_plain_blit", False)
            return
        st = probe_private(self, "_tx_state", None)
        if st is not None and st.any_active():
            object.__setattr__(self, "_plain_blit", False)
            return
        # Static hue stamp alone is still plain-blit OK.
        object.__setattr__(self, "_plain_blit", True)

    def _frame_fx(self, *, sdf: bool = False):
        """Lazy FrameFx for the current cell (path; SDF when ``sdf=True``).

        Available at every quality so Halo / Rim / outline looks can stroke the
        real silhouette at low. Survival still uses cheaper paints for looks
        that have a ladder; Aura skips the SDF draw path via its own fidelity
        gate. Sprite Halo / Laser / Rim prefer SDF bands over MaskFilter path
        strokes. Rim uses the same GlowRim / SDF package at every quality.
        Assign-time warmup covers most cases; this is the cache-miss fallback.
        """
        from .atlas import frame_fx_for_frame
        if self._play_frames:
            idx = self._current_frame_index()
        else:
            idx = int(self._frame)
        fr = self._sheet._frame_at(idx)
        img = self._sheet._image_for_frame(idx)
        return frame_fx_for_frame(img, fr, sdf=bool(sdf))

    def _path_polyline(self, path) -> List[Tuple[float, float]]:
        """On-curve points of a line-only silhouette path (0–1, y-down)."""
        if path is None or path.isEmpty():
            return []
        n = int(path.countPoints())
        out: List[Tuple[float, float]] = []
        for i in range(n):
            p = path.getPoint(i)
            out.append((float(p.x()), float(p.y())))
        if (
            len(out) >= 2
            and abs(out[0][0] - out[-1][0]) < 1e-5
            and abs(out[0][1] - out[-1][1]) < 1e-5
        ):
            out.pop()
        return out

    def _silhouette_paint_pose(
        self, cx: float, cy: float,
    ) -> Tuple[float, float, float, float, float, float, float, float]:
        """``(cx, cy, draw_ang, tilt, pivot_x, pivot_y, seat_x, seat_y)``."""
        draw_ang = self._draw_angle()
        tilt = self._tilt_angle_for_paint()
        px, py = self._tilt_pivot_local()
        sx, sy = self._tilt_seat_local(cx, cy)
        return cx, cy, draw_ang, tilt, px, py, sx, sy

    def _map_silhouette_local(
        self,
        lx: float,
        ly: float,
        *,
        flip_x: float,
        flip_y: float,
        draw_ang: float,
        tilt: float,
        px: float,
        py: float,
        sx: float = 0.0,
        sy: float = 0.0,
    ) -> Tuple[float, float]:
        """dst-space point → y-up local, same order as ``_apply_paint_xform``."""
        x = float(flip_x) * lx
        y = -float(flip_y) * ly
        if abs(tilt) > 1e-12:
            x -= px
            y -= py
            rad = math.radians(float(tilt))
            c, s = math.cos(rad), math.sin(rad)
            x, y = c * x - s * y, s * x + c * y
            x += px
            y += py
        x += float(sx)
        y += float(sy)
        if abs(draw_ang) > 1e-12:
            rad = math.radians(float(draw_ang))
            c, s = math.cos(rad), math.sin(rad)
            x, y = c * x - s * y, s * x + c * y
        return x, y

    def _design_box_world_verts(self) -> List[Tuple[float, float]]:
        """Closed design-box corners when the silhouette path is empty."""
        loc = self._blit_local_dst()
        if loc is None:
            cx, cy = get_xy(self.center, bare=True)
            return [(cx, cy)]
        cx, cy, _ang, flip_x, flip_y, dst, _fr, _idx = loc
        cx, cy, draw_ang, tilt, px, py, sx, sy = self._silhouette_paint_pose(cx, cy)
        corners = (
            (dst.left(), dst.top()),
            (dst.right(), dst.top()),
            (dst.right(), dst.bottom()),
            (dst.left(), dst.bottom()),
        )
        out = []
        for lx, ly in corners:
            x, y = self._map_silhouette_local(
                lx, ly, flip_x=flip_x, flip_y=flip_y,
                draw_ang=draw_ang, tilt=tilt, px=px, py=py, sx=sx, sy=sy,
            )
            out.append((cx + x, cy + y))
        return out

    def _silhouette_world_verts(self) -> List[Tuple[float, float]]:
        """World polyline of the current cell's FrameFx silhouette.

        Lazy-bakes the path cache. Empty art falls back to the design box.
        """
        fx = self._frame_fx()
        src = None
        if fx is not None and not fx.empty:
            src = fx.path
        pts = self._path_polyline(src)
        loc = self._blit_local_dst()
        if loc is None or len(pts) < 3:
            return self._design_box_world_verts()
        cx, cy, _ang, flip_x, flip_y, dst, _fr, _idx = loc
        cx, cy, draw_ang, tilt, px, py, sx, sy = self._silhouette_paint_pose(cx, cy)
        left, top = float(dst.left()), float(dst.top())
        dw, dh = float(dst.width()), float(dst.height())
        out: List[Tuple[float, float]] = []
        for u, v in pts:
            x, y = self._map_silhouette_local(
                left + u * dw, top + v * dh,
                flip_x=flip_x, flip_y=flip_y,
                draw_ang=draw_ang, tilt=tilt, px=px, py=py, sx=sx, sy=sy,
            )
            out.append((cx + x, cy + y))
        return out

    def _blit_local_dst(self):
        """Return (cx, cy, ang, fx, fy, dst_rect, fr) for the current frame blit."""
        cx, cy = get_xy(self.center, bare=True)
        if self._play_frames:
            idx = self._current_frame_index()
            self._frame = idx
        else:
            idx = int(self._frame)
        fr = self._sheet._frame_at(idx)
        sx, sy = self._pixel_scale(fr)
        du_w = abs(float(fr.src_w)) * sx
        du_h = abs(float(fr.src_h)) * sy
        if du_w <= 0.0 or du_h <= 0.0:
            return None
        left = (float(fr.src_x) - float(fr.pivot_x) * float(fr.src_w)) * sx
        top = (float(fr.src_y) - float(fr.pivot_y) * float(fr.src_h)) * sy
        packed_w = float(fr.h if fr.rotated else fr.w)
        packed_h = float(fr.w if fr.rotated else fr.h)
        dw = packed_w * sx
        dh = packed_h * sy
        ox, oy = self._offset_x, self._offset_y
        fx = -1.0 if self._flip_x else 1.0
        fy = -1.0 if self._flip_y else 1.0
        dst = skia.Rect.MakeXYWH(left + ox, top - oy, dw, dh)
        # ``ang`` is total paint angle for callers that only need a scalar;
        # draw paths should use ``_apply_paint_xform`` so tilt pivots correctly.
        ang = self._paint_angle()
        return cx, cy, ang, fx, fy, dst, fr, idx

    def _draw_sprite_silhouette(self, skia_canvas: skia.Canvas, paint) -> bool:
        """Stroke/fill the cached silhouette path. Returns True if drawn."""
        if paint is None:
            return False
        fx = self._frame_fx()
        if fx is None or fx.empty or fx.path is None or fx.path.isEmpty():
            return False
        loc = self._blit_local_dst()
        if loc is None:
            return False
        cx, cy, ang, flip_x, flip_y, dst, fr, _idx = loc
        skia_canvas.save()
        self._apply_paint_xform(skia_canvas, cx, cy, flip_x, flip_y)
        # Path is 0–1 in packed cell; map into dst.
        m = skia.Matrix.Translate(dst.left(), dst.top())
        m.preScale(dst.width(), dst.height())
        path = skia.Path(fx.path)
        path.transform(m)
        skia_canvas.drawPath(path, paint)
        skia_canvas.restore()
        return True

    def _local_silhouette_path_v2(self):
        """Cached local-pixel simplified path + blit loc. None if unavailable."""
        from .atlas import _FX_LOCAL_V2_CACHE_MAX
        fx = self._frame_fx()
        if fx is None or fx.empty:
            return None
        src = fx.path_v2 if (fx.path_v2 is not None and not fx.path_v2.isEmpty()) else fx.path
        if src is None or src.isEmpty():
            return None
        loc = self._blit_local_dst()
        if loc is None:
            return None
        _cx, _cy, _ang, _fx, _fy, dst, _fr, _idx = loc
        key = (
            round(float(dst.left()), 2), round(float(dst.top()), 2),
            round(float(dst.width()), 2), round(float(dst.height()), 2),
        )
        cache = fx.local_v2
        if cache is None:
            cache = {}
            fx.local_v2 = cache
        hit = cache.get(key)
        if hit is None:
            m = skia.Matrix.Translate(dst.left(), dst.top())
            m.preScale(dst.width(), dst.height())
            hit = skia.Path(src)
            hit.transform(m)
            if len(cache) >= _FX_LOCAL_V2_CACHE_MAX:
                cache.clear()
            cache[key] = hit
        return hit, loc

    def _draw_sprite_silhouette_v2(self, skia_canvas: skia.Canvas, paint) -> bool:
        """Stroke/fill the simplified cached silhouette. Returns True if drawn."""
        if paint is None:
            return False
        packed = self._local_silhouette_path_v2()
        if packed is None:
            return self._draw_sprite_silhouette(skia_canvas, paint)
        path, loc = packed
        cx, cy, ang, flip_x, flip_y, _dst, _fr, _idx = loc
        skia_canvas.save()
        self._apply_paint_xform(skia_canvas, cx, cy, flip_x, flip_y)
        skia_canvas.drawPath(path, paint)
        skia_canvas.restore()
        return True

    def _sdf_width_from_px(self, fx, dst, px: float) -> float:
        """World-pixel stroke width → sprite_aura / sprite_sil_v2 ``d`` units."""
        max_side = float(max(fx.mw, fx.mh, 1))
        scale = 128.0 / max(max_side * 0.5, 8.0)
        d_per_bake = scale / 127.5
        world_w = max(float(dst.width()), 1e-6)
        bake_per_world = float(fx.mw) / world_w
        return max(0.001, float(px) * bake_per_world * d_per_bake)

    def _draw_sprite_sdf_bands(
        self,
        skia_canvas: skia.Canvas,
        rgba,
        *,
        glow_width: float = 0.0,
        glow_alpha: float = 0.0,
        rim_width: float = 0.0,
        rim_alpha: float = 0.0,
        core_width: float = 0.0,
        core_alpha: float = 0.0,
    ) -> bool:
        """One ADD SDF quad: outer glow + rim + white core. Widths in world px."""
        from ._sksl_shape import procedural_builder
        if (glow_alpha <= 1e-4 and rim_alpha <= 1e-4 and core_alpha <= 1e-4):
            return False
        fx = self._frame_fx(sdf=True)
        if fx is None or fx.empty or fx.sdf is None:
            return False
        loc = self._blit_local_dst()
        if loc is None:
            return False
        cx, cy, ang, flip_x, flip_y, dst, _fr, _idx = loc
        pad = float(fx.pad)
        mw = float(max(fx.mw, 1))
        mh = float(max(fx.mh, 1))
        pad_x = dst.width() * (pad / mw)
        pad_y = dst.height() * (pad / mh)
        outer = skia.Rect.MakeLTRB(
            dst.left() - pad_x, dst.top() - pad_y,
            dst.right() + pad_x, dst.bottom() + pad_y,
        )
        gw = self._sdf_width_from_px(fx, dst, glow_width) if glow_alpha > 1e-4 else 0.001
        rw = self._sdf_width_from_px(fx, dst, rim_width) if rim_alpha > 1e-4 else 0.001
        cw = self._sdf_width_from_px(fx, dst, core_width) if core_alpha > 1e-4 else 0.001
        b = procedural_builder("sprite_sil_v2")
        sh_img = fx.sdf.makeShader(
            skia.TileMode.kClamp, skia.TileMode.kClamp,
            skia.SamplingOptions(skia.FilterMode.kLinear),
        )
        b.setChild("u_sdf", sh_img)
        r, g, bl, a = float(rgba[0]), float(rgba[1]), float(rgba[2]), float(rgba[3]) if len(rgba) > 3 else 1.0
        b.setUniform("u_color", [r, g, bl, a])
        b.setUniform("u_glow_w", float(gw))
        b.setUniform("u_glow_a", float(glow_alpha) * a)
        b.setUniform("u_rim_w", float(rw))
        b.setUniform("u_rim_a", float(rim_alpha) * a)
        b.setUniform("u_core_w", float(cw))
        b.setUniform("u_core_a", float(core_alpha) * a)
        b.setUniform(
            "u_dst",
            [outer.left(), outer.top(), outer.right(), outer.bottom()],
        )
        b.setUniform(
            "u_sdf_wh", [float(fx.sdf.width()), float(fx.sdf.height())],
        )
        paint = skia.Paint(
            AntiAlias=True, Shader=b.makeShader(), BlendMode=skia.BlendMode.kPlus,
        )
        skia_canvas.save()
        self._apply_paint_xform(skia_canvas, cx, cy, flip_x, flip_y)
        skia_canvas.drawRect(outer, paint)
        skia_canvas.restore()
        return True

    def _draw_sprite_aura(self, skia_canvas: skia.Canvas, look) -> None:
        """Draw SDF aura quad under the sprite pose."""
        from ._sksl_shape import procedural_builder
        fx = self._frame_fx(sdf=True)
        if fx is None or fx.empty or fx.sdf is None:
            return
        loc = self._blit_local_dst()
        if loc is None:
            return
        cx, cy, ang, flip_x, flip_y, dst, fr, _idx = loc
        # Expand dst by SDF pad so the fringe can fall off (matches bake).
        pad = float(fx.pad)
        mw = float(max(fx.mw, 1))
        mh = float(max(fx.mh, 1))
        pad_x = dst.width() * (pad / mw)
        pad_y = dst.height() * (pad / mh)
        outer = skia.Rect.MakeLTRB(
            dst.left() - pad_x, dst.top() - pad_y,
            dst.right() + pad_x, dst.bottom() + pad_y,
        )
        b = procedural_builder("sprite_aura")
        # Child localMatrix is unreliable inside RuntimeEffects in py-skia —
        # map local → SDF texels with u_dst / u_sdf_wh instead.
        sh_img = fx.sdf.makeShader(
            skia.TileMode.kClamp, skia.TileMode.kClamp,
            skia.SamplingOptions(skia.FilterMode.kLinear),
        )
        b.setChild("u_sdf", sh_img)
        rgba = look._rgba
        b.setUniform("u_color", [rgba[0], rgba[1], rgba[2], rgba[3]])
        b.setUniform("u_amount", float(look.amount))
        b.setUniform("u_width", float(look.width))
        b.setUniform(
            "u_dst",
            [outer.left(), outer.top(), outer.right(), outer.bottom()],
        )
        b.setUniform(
            "u_sdf_wh", [float(fx.sdf.width()), float(fx.sdf.height())],
        )
        paint = skia.Paint(
            AntiAlias=True, Shader=b.makeShader(), BlendMode=skia.BlendMode.kPlus,
        )
        skia_canvas.save()
        self._apply_paint_xform(skia_canvas, cx, cy, flip_x, flip_y)
        skia_canvas.drawRect(outer, paint)
        skia_canvas.restore()

    def _draw_sprite_recolor(self, skia_canvas: skia.Canvas, look) -> None:
        """Blit current frame through hue-band Recolor SkSL."""
        from ._sksl_shape import procedural_builder
        loc = self._blit_local_dst()
        if loc is None:
            return
        cx, cy, ang, flip_x, flip_y, dst, fr, idx = loc
        src = self._sheet._src_rect(idx)
        img = self._sheet._image_for_frame(idx)
        b = procedural_builder("sprite_recolor")
        img_sh = img.makeShader(
            skia.TileMode.kClamp, skia.TileMode.kClamp, _SAMPLING,
        )
        b.setChild("u_image", img_sh)
        b.setUniform(
            "u_src", [src.left(), src.top(), src.right(), src.bottom()],
        )
        b.setUniform(
            "u_dst", [dst.left(), dst.top(), dst.right(), dst.bottom()],
        )
        kh, ks, kv = look._key_hsv
        th, ts, tv = look._to_hsv
        b.setUniform("u_key_hsv", [float(kh), float(ks), float(kv)])
        b.setUniform("u_to_hsv", [float(th), float(ts), float(tv)])
        b.setUniform("u_range", float(look.range))
        b.setUniform("u_soft", float(look.soft))
        shader = b.makeShader()
        paint = skia.Paint(AntiAlias=True, Shader=shader)
        # The body's gray, blend and alpha, as on every other body route (PB8:
        # a Recolor ignored Sprite.alpha and blend).
        self._apply_blit_paint_extras(paint)
        skia_canvas.save()
        self._apply_paint_xform(skia_canvas, cx, cy, flip_x, flip_y)
        if fr.rotated:
            skia_canvas.save()
            skia_canvas.translate(dst.left() + dst.width() * 0.5,
                                  dst.top() + dst.height() * 0.5)
            skia_canvas.rotate(-90.0)
            rdst = skia.Rect.MakeXYWH(-dst.height() * 0.5, -dst.width() * 0.5,
                                     dst.height(), dst.width())
            b.setUniform(
                "u_dst",
                [rdst.left(), rdst.top(), rdst.right(), rdst.bottom()],
            )
            paint.setShader(b.makeShader())       # keeps gray / blend / alpha (PB8)
            skia_canvas.drawRect(rdst, paint)
            skia_canvas.restore()
        else:
            skia_canvas.drawRect(dst, paint)
        skia_canvas.restore()

    def _blit_plain(self, skia_canvas: skia.Canvas) -> None:
        """Textured quad without the effect envelope.

        Pulls linked ``angle`` / ``scale`` PropertyAnchors first — this path
        skips ``Graphic.draw``, which is otherwise the only place that refreshes
        those slots before reading raw ``_rotation`` / ``_scale``.
        """
        paint = getattr(self, "_blit_paint", None)
        if paint is None:
            return
        self._pull_property_anchors()
        self._blit_image(skia_canvas, paint)

    def _blit_image(self, skia_canvas: skia.Canvas, paint) -> None:
        """Draw the current frame at the sprite pose."""
        if paint is None:
            return
        # Live hue: replace paint with SkSL image shader
        if getattr(self, "_blit_hue_live", None) is not None and paint is self._blit_paint:
            self._blit_hue_sksl(skia_canvas)
            return
        if self._play_frames:
            idx = self._current_frame_index()
            self._frame = idx
        else:
            idx = int(self._frame)
        sheet = self._sheet
        plan = self._blit_plan
        if plan is not None and _BLIT_PLAN:
            # A cached plan (Sprite Design, "Blit plan cache"): valid while the
            # pose revision, the cell and the sheet layout hold. The paint is
            # read live, so a paint write keeps it. A revision that moved only
            # by moves of the marked center (the pose cell's ``moves``, as the
            # cull's shift) keeps the plan at the new center.
            d = self.__dict__
            cell = d.get("_pose_cell")
            if (cell is not None and plan[2] == idx and plan[3] is sheet
                    and plan[4] == sheet._layout_epoch):
                rev = cell[0]
                if rev == plan[0]:
                    cx = plan[5]
                    cy = plan[6]
                elif plan[1] >= 0 and rev - plan[0] == cell[4] - plan[1]:
                    pd = d["center"].__dict__
                    cx = pd.get("x", 0.0)
                    cy = pd.get("y", 0.0)
                    plan = (rev, cell[4], idx, sheet, plan[4], cx, cy, plan[7])
                    object.__setattr__(self, "_blit_plan", plan)
                else:
                    plan = None
            else:
                plan = None
            if plan is not None:
                if _plan_verify():
                    self._verify_blit_plan(plan, idx)
                _draw_blit(skia_canvas, cx, cy, plan[7],
                           gpu_image(sheet._image_for_frame(idx), skia_canvas), paint)
                return
            object.__setattr__(self, "_blit_plan", None)
        if _BLIT_PLAN:
            # Stored once the pose held, or moved only by moves of the
            # marked center, since the last draw: ``revision - moves`` did
            # not change. A body that turns or resizes every frame pays this
            # compare and one store, and draws inline below.
            cell = self.__dict__.get("_pose_cell")
            if cell is not None:
                still = cell[0] - cell[4]
                seen = cell[5]
                if seen == still:
                    geo = self._blit_geometry(idx)
                    if geo is None:
                        return
                    self._store_blit_plan(idx, sheet, geo, cell)
                    _draw_blit(skia_canvas, geo[0], geo[1], geo[2],
                               gpu_image(sheet._image_for_frame(idx), skia_canvas), paint)
                    return
                cell[5] = still
                if seen is None:
                    self._mark_blit_mover(cell)
        # The same steps as ``_blit_geometry`` + ``_draw_blit``, inline: the
        # path of a body that changes every frame (tests compare the two).
        cx, cy = get_xy(self.center, bare=True)
        cache = self._src_rect_cache
        epoch = sheet._layout_epoch
        if cache is None or cache[0] != idx or cache[3] != epoch:
            fr = sheet._frame_at(idx)
            src = sheet._src_rect(idx)
            self._src_rect_cache = (idx, src, fr, epoch)
        else:
            src = cache[1]
            fr = cache[2]
        sx, sy = self._pixel_scale(fr)
        if sx <= 0.0 or sy <= 0.0:
            return
        left = (float(fr.src_x) - float(fr.pivot_x) * float(fr.src_w)) * sx
        top = (float(fr.src_y) - float(fr.pivot_y) * float(fr.src_h)) * sy
        packed_w = float(fr.h if fr.rotated else fr.w)
        packed_h = float(fr.w if fr.rotated else fr.h)
        dw = packed_w * sx
        dh = packed_h * sy
        ox, oy = self._offset_x, self._offset_y
        fx = -1.0 if self._flip_x else 1.0
        fy = -1.0 if self._flip_y else 1.0

        skia_canvas.save()
        self._apply_paint_xform(skia_canvas, cx, cy, fx, fy)
        if fr.rotated:
            skia_canvas.translate(left + ox + dw * 0.5, top - oy + dh * 0.5)
            skia_canvas.rotate(-90.0)
            dst = skia.Rect.MakeXYWH(-dh * 0.5, -dw * 0.5, dh, dw)
        else:
            dst = skia.Rect.MakeXYWH(left + ox, top - oy, dw, dh)
        skia_canvas.drawImageRect(
            gpu_image(sheet._image_for_frame(idx), skia_canvas), src, dst, _SAMPLING, paint,
        )
        skia_canvas.restore()

    def _blit_geometry(self, idx: int):
        """``(cx, cy, ops)`` of the cell ``idx`` at the current pose, or None
        when the scale is degenerate (nothing draws). ``ops`` are the
        transform steps after the translation to ``(cx, cy)`` (the same as
        ``_apply_paint_xform``, then a packed atlas's rotated cell) with the
        source and destination rects; ``_draw_blit`` applies them."""
        cx, cy = get_xy(self.center, bare=True)
        cache = self._src_rect_cache
        epoch = self._sheet._layout_epoch
        if cache is None or cache[0] != idx or cache[3] != epoch:
            fr = self._sheet._frame_at(idx)
            src = self._sheet._src_rect(idx)
            self._src_rect_cache = (idx, src, fr, epoch)
        else:
            src = cache[1]
            fr = cache[2]
        sx, sy = self._pixel_scale(fr)
        if sx <= 0.0 or sy <= 0.0:
            return None
        left = (float(fr.src_x) - float(fr.pivot_x) * float(fr.src_w)) * sx
        top = (float(fr.src_y) - float(fr.pivot_y) * float(fr.src_h)) * sy
        packed_w = float(fr.h if fr.rotated else fr.w)
        packed_h = float(fr.w if fr.rotated else fr.h)
        dw = packed_w * sx
        dh = packed_h * sy
        ox, oy = self._offset_x, self._offset_y
        fx = -1.0 if self._flip_x else 1.0
        fy = -1.0 if self._flip_y else 1.0
        draw_ang = self._draw_angle()
        tilt = self._tilt_angle_for_paint()
        seat_x, seat_y = self._tilt_seat_local(cx, cy)
        seat = (seat_x, seat_y) if abs(seat_x) > 1e-12 or abs(seat_y) > 1e-12 else None
        lean = (*self._tilt_pivot_local(), tilt) if abs(tilt) > 1e-12 else None
        if fr.rotated:
            turn = (left + ox + dw * 0.5, top - oy + dh * 0.5)
            dst = skia.Rect.MakeXYWH(-dh * 0.5, -dw * 0.5, dh, dw)
        else:
            turn = None
            dst = skia.Rect.MakeXYWH(left + ox, top - oy, dw, dh)
        return cx, cy, (draw_ang, seat, lean, fx, fy, turn, src, dst)

    def _mark_blit_mover(self, cell) -> None:
        """First draw: mark the center so its moves are counted in the pose
        cell (the cull's shift marks it the same way, ``canvas._cull_mover``),
        so a body that moves from birth still gets a plan."""
        global _pose_rev_of_fn, _cull_mover_fn
        if _cull_mover_fn is None:
            from .collision import _pose_rev_of as rev_of
            from .canvas import _cull_mover as mover
            _pose_rev_of_fn = rev_of
            _cull_mover_fn = mover
        _cull_mover_fn(self, cell)

    def _store_blit_plan(self, idx: int, sheet, geo, cell) -> None:
        """Keep ``geo`` as the blit plan when the pose revision can be
        trusted: a plain Sprite kind with no link or anchor
        (``collision._pose_rev_of``), no transient, and a bare tilt angle (a
        contact tilt or seat leans with live contacts)."""
        if _pose_rev_of_fn is None:
            self._mark_blit_mover(cell)
        raw = cell[0]
        if (_pose_rev_of_fn(self) != raw or getattr(self, "_tx_state", None) is not None
                or self._tilt_mode != "angle"):
            return
        # A body whose center cannot be marked (seated) keeps the plan per
        # revision only.
        moves = cell[4] if _cull_mover_fn(self, cell) is not None else -1
        object.__setattr__(self, "_blit_plan", (
            raw, moves, idx, sheet, sheet._layout_epoch, geo[0], geo[1], geo[2]))

    def _verify_blit_plan(self, plan, idx: int) -> None:
        """Verify mode: a cached plan must equal a fresh one."""
        fresh = _plain_geo(self._blit_geometry(idx))
        used = _plain_geo((plan[5], plan[6], plan[7]))
        if fresh != used:
            raise AssertionError(
                f"cached blit plan {used} != fresh {fresh} for {self!r}: "
                "a draw input changed with no pose revision")

    def _blit_hue_sksl(self, skia_canvas: skia.Canvas) -> None:
        from ._sksl_shape import procedural_builder
        loc = self._blit_local_dst()
        if loc is None:
            return
        cx, cy, ang, flip_x, flip_y, dst, fr, idx = loc
        src = self._sheet._src_rect(idx)
        img = self._sheet._image_for_frame(idx)
        b = procedural_builder("sprite_hue")
        img_sh = img.makeShader(
            skia.TileMode.kClamp, skia.TileMode.kClamp, _SAMPLING,
        )
        b.setChild("u_image", img_sh)
        b.setUniform(
            "u_src", [src.left(), src.top(), src.right(), src.bottom()],
        )
        b.setUniform(
            "u_dst", [dst.left(), dst.top(), dst.right(), dst.bottom()],
        )
        b.setUniform("u_amount", float(self._blit_hue_live or 0.0))
        paint = skia.Paint(AntiAlias=True, Shader=b.makeShader())
        self._apply_blit_paint_extras(paint)
        skia_canvas.save()
        self._apply_paint_xform(skia_canvas, cx, cy, flip_x, flip_y)
        if fr.rotated:
            skia_canvas.save()
            skia_canvas.translate(
                dst.left() + dst.width() * 0.5,
                dst.top() + dst.height() * 0.5,
            )
            skia_canvas.rotate(-90.0)
            rdst = skia.Rect.MakeXYWH(
                -dst.height() * 0.5, -dst.width() * 0.5,
                dst.height(), dst.width(),
            )
            b.setUniform(
                "u_dst",
                [rdst.left(), rdst.top(), rdst.right(), rdst.bottom()],
            )
            hue_paint = skia.Paint(AntiAlias=True, Shader=b.makeShader())
            self._apply_blit_paint_extras(hue_paint)
            skia_canvas.drawRect(rdst, hue_paint)
            skia_canvas.restore()
        else:
            skia_canvas.drawRect(dst, paint)
        skia_canvas.restore()

    def _geometry_draw(
        self,
        skia_canvas: skia.Canvas,
        fill_paint=_STYLE_PAINT,
        stroke_paint=_STYLE_PAINT,
    ) -> None:
        """Blit the image body; costume fills/strokes use the sprite silhouette.

        * ``fill_paint is _STYLE_PAINT`` — optional look fill as silhouette/ellipse
          under the bitmap, then blit. ``SPRITE_BODY`` fill is not painted as a
          solid. Looks with ``_replaces_sprite_body`` skip the blit so the material
          shows.
        * explicit ``fill_paint`` — Tail (role E) ghosts blit with that paint;
          other Fill-style paints fill the silhouette (Extrude slabs, Metal, …).
        * stroke (style or override) — silhouette path when available.
        """
        do_blit = False
        blit_paint = None
        ellipse_fill = None
        ellipse_stroke = None
        vis = getattr(self, "_visual", None)
        replace_body = bool(vis is not None and getattr(vis, "_replaces_sprite_body", False))

        if fill_paint is _STYLE_PAINT:
            fill = getattr(self, "_fill", None)
            # A style fill / line is a look's costume. With no look the full
            # path draws what the plain blit draws: the bitmap (PB7:
            # ``sprite.color = "blue"`` stroked an outline on this path only).
            if vis is not None and fill is not None and not is_sprite_body(fill):
                ellipse_fill = self._to_skia_fill_paint()
            if replace_body:
                do_blit = False
            else:
                do_blit = True
                blit_paint = self._blit_paint
        elif fill_paint is not None:
            # Tail / motion ghosts (role E or stamp ghosting): tinted blit.
            # Body / depth fills: paint the silhouette without covering with blit.
            role = getattr(vis, "_color_role", None) if vis is not None else None
            ghosting = bool(getattr(self, "_tail_ghosting", False))
            try:
                is_fill_style = fill_paint.getStyle() == skia.Paint.kFill_Style
            except Exception:
                is_fill_style = False
            if is_fill_style and not ghosting and role != "E":
                ellipse_fill = fill_paint
                do_blit = False
            else:
                do_blit = True
                blit_paint = fill_paint

        if stroke_paint is _STYLE_PAINT:
            ellipse_stroke = self._to_skia_line_paint() if vis is not None else None
        elif stroke_paint is not None:
            ellipse_stroke = stroke_paint

        if ellipse_fill is not None:
            self._draw_sprite_ellipse(skia_canvas, ellipse_fill)
        if do_blit:
            self._blit_image(skia_canvas, blit_paint)
        if ellipse_stroke is not None:
            self._draw_sprite_ellipse(skia_canvas, ellipse_stroke)

    def __str__(self) -> str:
        src = getattr(self._sheet, "_display", None) or getattr(self._sheet, "_source", "?")
        from .entity import made_at
        where = made_at(self)
        return f"Sprite({src!r}, {where})" if where else f"Sprite({src!r})"

    def __repr__(self) -> str:
        return self.__str__()


def _add_hitbox_signature():
    import inspect as _inspect
    kw = _inspect.Parameter.KEYWORD_ONLY
    return _inspect.Signature([
        _inspect.Parameter("self", _inspect.Parameter.POSITIONAL_OR_KEYWORD),
        _inspect.Parameter("group", kw, default=None),
        _inspect.Parameter("shape", kw, default="auto"),
        _inspect.Parameter("source", kw, default="each"),
        _inspect.Parameter("anchor", kw, default="center"),
        _inspect.Parameter("scale", kw, default=1.0),
        _inspect.Parameter("active", kw, default=True),
        _inspect.Parameter("px_rect", kw, default=None),
        _inspect.Parameter("px_circle", kw, default=None),
    ])


# Readable defaults for help() / IDEs; the real defaults are the sentinel.
Sprite.add_hitbox.__signature__ = _add_hitbox_signature()



class Svg(Sprite):
    """Sprite whose pixels come from SVG markup or an SVG file.

    ``Svg("<svg …>", height=48)`` or ``Svg("heart.svg", height=48)`` rasterizes
    once into a private single-frame sheet. A string containing ``<`` is
    markup; otherwise it is a filename (same resolve as Sprite). ``.svg``
    always stores markup (file contents after load, never the path). Writing
    ``.svg`` uses the same rule (same stored markup is a no-op). Still only —
    no sheet clips / ``play``. ``isinstance(svg, Sprite)`` is
    True; ``isinstance(svg, Shape)`` is False.

    Args:
        source: SVG markup or an ``.svg`` file.
        center: Pivot position (with a bottom-anchored Sheet, the feet).
        width: Width in design units (alone: keeps the aspect; with ``height``:
            stretches).
        height: Height in design units.
        size: Longer side in design units (keeps the aspect; not with ``width`` /
            ``height``).
        hitbox_shape: The main hitbox's shape: ``"auto"`` (default) · ``"rect"`` ·
            ``"ellipse"`` · ``"circle"`` · ``"hull"`` (then ``sprite.hitbox.shape``).
        hitbox_source: Which art the main hitbox is measured on: a frame, a clip,
            ``"all"`` · ``"clip"`` · ``"each"`` (then ``sprite.hitbox.source``).
        hitbox_anchor: Point that stays put when the main hitbox is scaled
            (``"center"``, ``"bottom"``, …; then ``sprite.hitbox.anchor``).
        hitbox_scale: Shrink / stretch the main hitbox: a number or ``(sx, sy)``
            (then ``sprite.hitbox.scale``).
        shield_scale: Size of the Shield / Electric* envelope around the art (default
            1.4).
        offset: Shift ``(dx, dy)`` of the picture and collider from ``center``.
        visual: A look (``Halo()``, ``Metal()``, …).
        group: Group tag(s).
        flip_x: Mirror left-right.
        flip_y: Mirror up-down.
        art_angle: Heading the image is drawn facing, in degrees (so angle 0 means
            “facing +x”).
        angle: Heading at construction — where the painted front points, in
            degrees (default: ``rest_heading``, so the sprite appears as drawn).
        box: Fit into a Box (keeps the image aspect).
        layer: Draw layer (default ``"default"``).
    """

    __slots__ = ("_svg",)
    _clone_takes_frame = False      # a still: clone(frame=) refuses (Graphic.clone)

    def __init__(
        self,
        source: Optional[str] = None,
        *,
        center: Optional[GeneralPoint] = None,
        width: Any = _OMIT,
        height: Any = _OMIT,
        size: Any = _OMIT,
        hitbox_shape: Any = _OMIT,
        hitbox_source: Any = _OMIT,
        hitbox_anchor: Any = _OMIT,
        hitbox_scale: Any = _OMIT,
        shield_scale: Any = _OMIT,
        offset: Any = _OMIT,
        visual: Any = _OMIT,
        group: Any = _OMIT,
        flip_x: Any = _OMIT,
        flip_y: Any = _OMIT,
        art_angle: Any = _OMIT,
        angle: Any = _OMIT,
        box: Any = _OMIT,
        layer: Any = _USE_LAYER_DEFAULT,
        **kwargs,
    ):
        frame = kwargs.pop("frame", _OMIT)
        _reject_unexpected_sprite_kwargs(type(self).__name__, kwargs)
        if frame is not _OMIT and frame not in (0, "0"):
            raise TypeError(
                "Svg is a still — frame= is not supported. "
                'Write Svg("<svg …>", height=48) or Svg("icon.svg").'
            )

        source = as_payload(source)
        defaults = getattr(type(self), "_sprite_defaults", None) or {}
        if source is None and "source" in defaults:
            source = as_payload(defaults["source"])

        text: Optional[str]
        if source is None:
            text = None
        elif isinstance(source, str):
            text = source
        else:
            raise TypeError(
                "Svg expected a string (SVG markup or filename), "
                "or omit for a placeholder. "
                f"Got {type(source).__name__}."
            )

        dest_longer = _svg_dest_longer_from_kwargs(
            width=width if width is not _OMIT else defaults.get("width"),
            height=height if height is not _OMIT else defaults.get("height"),
            size=size if size is not _OMIT else defaults.get("size"),
        )
        sized = any(
            (v if v is not _OMIT else defaults.get(k)) is not None
            for k, v in (("width", width), ("height", height), ("size", size))
        )
        if not sized and box is not _OMIT and box is not None:
            # box= alone: the drawing fills the region, so raster at its size
            # (it rastered at the 128 default and drew blurred in a big box:
            # SF2 in Testing Design). A formula region: its first value.
            from .box import is_box_formula, region_frame
            region = box() if is_box_formula(box) else box
            _cx, _cy, rw, rh, _a = region_frame(region)
            longer = max(abs(float(rw)), abs(float(rh)))
            if longer > 0.0:
                dest_longer = longer

        img, ok, stored = _svg_resolve_source(text, dest_longer=dest_longer)
        sheet = _sheet_from_image(
            img,
            placeholder=not ok,
            display="svg" if ok else "svg-placeholder",
        )
        super().__init__(
            sheet,
            center=center,
            width=width,
            height=height,
            size=size,
            hitbox_shape=hitbox_shape,
            hitbox_source=hitbox_source,
            hitbox_anchor=hitbox_anchor,
            hitbox_scale=hitbox_scale,
            shield_scale=shield_scale,
            offset=offset,
            visual=visual,
            group=group,
            flip_x=flip_x,
            flip_y=flip_y,
            art_angle=art_angle,
            angle=angle,
            box=box,
            layer=layer,
        )
        self._owns_sheet = True
        self._sheet._shared = False
        self._sheet._interned = False
        self._svg = stored

    @property
    def svg(self) -> Optional[str]:
        """Current SVG markup, or ``None`` for an empty placeholder.

        Always markup (file contents after a filename load), never the path.
        Assign a markup string or a filename; same stored text is a no-op.
        """
        return self._svg

    @svg.setter
    def svg(self, value) -> None:
        value = as_payload(value)
        if value is None:
            text: Optional[str] = None
        elif isinstance(value, str):
            text = value
        else:
            raise TypeError(
                "svg expected a string (markup or filename) or None. "
                f"Got {type(value).__name__}."
            )
        if text is not None and text == self._svg:
            return
        had_good = not bool(getattr(self, "_placeholder", True)) and self._svg is not None
        dest = max(abs(float(self.width)), abs(float(self.height)), 1.0)
        img, ok, stored = _svg_resolve_source(text, dest_longer=dest)
        if stored is not None and stored == self._svg:
            return
        if not ok and had_good and text is not None:
            # Keep last good body and markup; warn already emitted. ``svg = None``
            # is a clear, not a failed load: it was a silent no-op (PB15).
            return
        sheet = _sheet_from_image(
            img,
            placeholder=not ok,
            display="svg" if ok else "svg-placeholder",
        )
        self._sheet = sheet
        self._owns_sheet = True
        self._placeholder = bool(sheet._placeholder)
        self._svg = stored
        self._src_rect_cache = None
        fr0 = sheet._frame_at(0)
        self._refit_box_to_art(float(fr0.src_w), float(fr0.src_h))
        self._ref_src_w = float(fr0.src_w)
        self._ref_src_h = float(fr0.src_h)
        self._frame = 0
        self._play_name = None
        self._play_frames = ()
        self._on_sheet_swapped()
        self._warm_frame_fx_for_visual()

    def _refit_box_to_art(self, px_w: float, px_h: float) -> None:
        """New art keeps the side the author sized and takes its own aspect
        (PB9: art of another aspect was stretched into the old box)."""
        if px_w <= 0.0 or px_h <= 0.0:
            return
        w, h = abs(float(self.width)), abs(float(self.height))
        intent = getattr(self, "_size_intent", None)
        if intent == "width":
            w2, h2 = w, w * px_h / px_w
        elif intent == "height":
            w2, h2 = h * px_w / px_h, h
        else:
            longer = max(w, h)
            w2, h2 = (longer, longer * px_h / px_w) if px_w >= px_h else (longer * px_w / px_h, longer)
        if abs(w2 - w) > 1e-9 or abs(h2 - h) > 1e-9:
            self.width = w2
            self.height = h2

    def play(self, clip: str, *, loops: Optional[int] = None, next: Optional[str] = None):
        """Refused: an Svg is a still (``TypeError``). Use a Sprite + Sheet for clips."""
        _refuse_if_destroyed(self, "play")
        raise TypeError(
            "Svg is a still — play() is not supported. "
            "Use Sprite for clips, or rewrite .svg to change the picture."
        )

    def _clone_recipe(self, *, center=None, frame=None, **kwargs) -> "Svg":
        """Construct a new Svg from this markup (private sheet; not shared)."""
        if center is None:
            center = get_xy(self.center, bare=True)
        return self._copy_main_hitbox_switch(type(self)(
            self._svg,
            hitbox_shape=self._hitbox_kind,
            hitbox_source=self._hitbox_from,
            hitbox_anchor=self._hitbox_anchor,
            hitbox_scale=self._hitbox_scale,
            shield_scale=self._shield_scale,
            offset=self.offset,
            flip_x=self._flip_x,
            flip_y=self._flip_y,
            art_angle=self._art_angle,
            center=center,
            **self._size_intent_kwargs(),
            **kwargs,
        ))

    def __str__(self) -> str:
        n = 0 if self._svg is None else len(self._svg)
        from .entity import made_at
        where = made_at(self)
        return f"Svg({n} chars, {where})" if where else f"Svg({n} chars)"


def _svg_dest_longer_from_kwargs(
    *,
    width: Any,
    height: Any,
    size: Any,
) -> float:
    """Guess dest longer side (design units) for first raster from construct kwargs."""
    vals = []
    for v in (width, height, size):
        if v is None or v is _OMIT:
            continue
        try:
            n = float(as_payload(v))
        except (TypeError, ValueError):
            continue
        if math.isfinite(n) and n > 0.0:
            vals.append(n)
    if vals:
        return max(vals)
    return float(_SVG_MIN_PX)


def _svg_resolve_source(
    text: Optional[str],
    *,
    dest_longer: Optional[float],
) -> Tuple[skia.Image, bool, Optional[str]]:
    """Return ``(image, ok, stored_markup)``.

    A string containing ``<`` is markup. Otherwise it is a filename (same
    resolve as Sprite). ``stored_markup`` is always contents, never a path.
    """
    if text is None or text == "":
        return _make_placeholder("svg"), False, None if text is None else ""
    if not _svg_looks_like_markup(text):
        source = text
        resolved = _resolve_image_path(source)
        if resolved is None:
            _svg_warn_once(
                "missing",
                source,
                f"Svg file not found: {source!r}. Using a placeholder. "
                "The actor is still valid "
                "(layer / groups / process still work).",
            )
            return _make_placeholder("svg"), False, None
        try:
            with open(resolved, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            _svg_warn_once(
                "read",
                source,
                f"Svg failed to read {source!r} ({e}). Using a placeholder. "
                "The actor is still valid.",
            )
            return _make_placeholder("svg"), False, None
        if not _svg_looks_like_markup(text):
            _svg_warn_once(
                "parse",
                source,
                f"Svg expected SVG markup in {source!r} (no '<' found). "
                "Using a placeholder. The actor is still valid.",
            )
            return _make_placeholder("svg"), False, None
    img, ok = _raster_svg(text, dest_longer=dest_longer)
    return img, ok, text


def _catalog_intern_key(source: str) -> Optional[tuple]:
    """Key for sharing a path-only single-frame catalog.

    Author ``Sheet(...)`` catalogs are never interned. Beginner
    ``Sprite(\"shot.png\")`` shares one still.
    """
    if not source or not isinstance(source, str):
        return None
    if is_atlas_filename(source):
        return None
    resolved = _resolve_image_path(source)
    ident = os.path.abspath(resolved) if resolved is not None else source
    return ("single", ident)


def _intern_get(key: tuple) -> Optional[Sheet]:
    hit = Sheet._intern.get(key)
    if hit is not None:
        hit._shared = True
        return hit
    return None


def _intern_put(key: tuple, sheet: Sheet) -> Sheet:
    sheet._interned = True
    sheet._shared = True
    Sheet._intern[key] = sheet
    return sheet


def _bind_source(source: Union[str, Sheet, None]) -> Sheet:
    """Return a Sheet. ``Sprite()`` → interned placeholder catalog."""
    source = as_payload(source)

    if source is None:
        hit = _intern_get(("placeholder",))
        if hit is not None:
            return hit
        img = _make_placeholder(None)
        sheet = _sheet_from_image(img, placeholder=True, display="placeholder")
        sheet._source = ""
        return _intern_put(("placeholder",), sheet)

    if isinstance(source, Sheet):
        if int(getattr(source, "_nframes", 0) or 0) < 1:
            raise ValueError(
                "Sprite needs at least one frame. This Sheet is empty — "
                "call sheet.strip(...) (or pass a file to Sheet) before Sprite(sheet)."
            )
        source._shared = True
        return source

    if isinstance(source, (list, tuple)):
        raise TypeError(
            "Sprite source is one still file or a Sheet. "
            'For several files write Sheet(["a.png", "b.png"]) then Sprite(sheet).'
        )
    if not isinstance(source, str):
        raise TypeError(
            "Sprite source expected a filename, a Sheet, or omit "
            f"for a placeholder; got {type(source).__name__}. "
            'Write Sprite("potion.png") or Sprite().'
        )
    if _is_file_pattern(source):
        raise TypeError(
            f"Sprite source is one still file; {source!r} is a file pattern "
            "(several frames). To play them write "
            f"Sprite(Sheet({source!r}, fps=8)); for one still, name the file."
        )
    if is_atlas_filename(source):
        raise TypeError(
            "Atlas catalogs belong on Sheet. "
            'Write Sheet("sheet.png", atlas="sheet.xml") then Sprite(sheet, ...).'
        )

    intern_key = _catalog_intern_key(source)
    if intern_key is not None:
        hit = _intern_get(intern_key)
        if hit is not None:
            return hit
    sheet = Sheet(source)
    if intern_key is not None:
        return _intern_put(intern_key, sheet)
    return sheet


def _publish_svg_signature() -> None:
    """``help(Svg)`` lists its keywords; ``**kwargs`` only catches ``frame=``
    (a still refuses it with the fix) and Sheet-only knobs."""
    import inspect as _inspect
    sig = _inspect.signature(Svg.__init__)
    Svg.__signature__ = sig.replace(parameters=[
        p for p in sig.parameters.values()
        if p.name != "self" and p.kind is not p.VAR_KEYWORD
    ])


_publish_svg_signature()
