"""Packed atlas loaders (TexturePacker JSON, Kenney XML) and auto-hitbox.

Used by ``Sheet`` / ``Sprite``. Not star-exported. Parse once per resolved
path; greedy alpha covering is cached per image region.
"""
from __future__ import annotations

import json
import math
import os
import warnings
import xml.etree.ElementTree as ET
from collections import OrderedDict, deque
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import skia


def _sq(v: float) -> float:
    """``v * v``. Not ``v ** 2``: a float power raises OverflowError for a
    huge-but-finite author coordinate; a product saturates to inf."""
    return v * v

# Auto-hitbox tuning (Slice 5). Refine with scripts/perf_sprite_hitbox.py.
_AUTO_MAX_SIDE = 32
_AUTO_ALPHA = 16
_AUTO_PRECISION_MIN = 0.90
_AUTO_QUALITY_BAR = 0.90
_AUTO_PRECISION_EXP = 1.5
_AUTO_HULL_MAX_VERTS = 8
_AUTO_HULL_PRECISION_GUARD = 0.92
# Soft stop already exists (target / diminishing gain). Hard cap keeps worst-case
# prim counts bounded — bench showed 6–8 boxes/circles explode broad-phase cost.
_AUTO_RECT_CAP = 5
_AUTO_CIRCLE_CAP = 5
_AUTO_RECT_TARGET = 0.95
_AUTO_RECT_DIMINISH_FLOOR = 0.80
_AUTO_RECT_MIN_GAIN = 0.02  # fraction of frame bbox area
# Runtime cost units (narrow-phase), used in utility = quality − λ × cost.
_AUTO_COST_CIRCLE = 1.0
_AUTO_COST_ELLIPSE = 2.0
_AUTO_COST_HULL = 2.0
_AUTO_COST_HULL_PER_VERT = 0.1
_AUTO_COST_AABB = 1.0  # forced boxes / lab only (auto never multi-AABB)
_AUTO_COST_OBB = 3.0  # 1-rect candidate costed as SAT OBB (sprites may rotate)
_AUTO_COST_LAMBDA = 0.05
# Axes within this ratio → treat fitted / geometric ellipse as a circle.
_AUTO_ELLIPSE_CIRCLE_RATIO = 1.08
# Two-ellipse residual must beat single-ellipse recall by at least this,
# and clear this absolute floor (avoids weak H+V splits on L-shapes).
_AUTO_TWO_ELLIPSE_MIN_GAIN = 0.05
_AUTO_TWO_ELLIPSE_MIN_RECALL = 0.75
# Multi-circle prefixes (k≥2) need at least this recall to be candidates.
_AUTO_CIRCLE_GATE = 0.75
# If any candidate clears the quality bar at high precision, discard severe undershoot.
_AUTO_RECALL_RAIL = True
_AUTO_RECALL_FLOOR = 0.75
# Legacy alias for tests that pass max_rects=
_AUTO_MAX_RECTS = _AUTO_RECT_CAP


def ellipse_as_circle(
    rx: float, ry: float, *, ratio: float = _AUTO_ELLIPSE_CIRCLE_RATIO,
) -> Optional[float]:
    """If ellipse axes are nearly equal, return mean radius; else ``None``."""
    ax, ay = abs(float(rx)), abs(float(ry))
    lo = min(ax, ay)
    if lo <= 1e-12:
        return None
    if max(ax, ay) / lo <= float(ratio):
        return 0.5 * (ax + ay)
    return None

# (image token, x, y, w, h, force_kind) → AutoCollider.
# The image token is the first live Sheet's token bound to that image, so every
# Sheet over one decoded image shares the bake. It survives image-id reuse: the
# binding (and its cache entries) drop when the last holding Sheet dies.
_ATLAS_CACHE_CAP = 128
_AUTO_CACHE: "OrderedDict[Tuple[Any, ...], AutoCollider]" = OrderedDict()
_MASK_CACHE: "OrderedDict[Tuple[Any, ...], np.ndarray]" = OrderedDict()
_UNION_CACHE: "OrderedDict[Tuple[Any, ...], AutoCollider]" = OrderedDict()
_FRAME_FX_CACHE: "OrderedDict[Tuple[Any, ...], FrameFx]" = OrderedDict()
_IMAGE_TOKEN: Dict[int, int] = {}
_IMAGE_HOLDERS: Dict[int, Set[int]] = {}
_SHEET_TOKEN = 0
_DOWNSAMPLE_WARNED = False
_FX_MAX_SIDE = 96
# Silhouette / SDF bake: solid if alpha ≥ this (0–255). 16 (~6%) matches
# hitbox auto-bake; fringe can sit slightly outside the perceived art edge.
_FX_ALPHA = 16
_FX_SDF_PAD = 20  # empty border so Aura fringe can fall off (not hard-crop)
# v2 silhouette: VW cap, then quadratic-smoothed path (rounded borders).
_FX_PATH_V2_MAX = 72
_FX_PATH_V1_CAP = 200
_FX_PATH_V1_TARGET = 160
_FX_LOCAL_V2_CACHE_MAX = 8

_ATLAS_CACHE: Dict[str, Tuple[Optional[str], Tuple["AtlasFrame", ...]]] = {}


class AtlasFrame:
    """One packed subtexture. Pixel space, y-down, origin top-left of the sheet."""

    __slots__ = (
        "name", "x", "y", "w", "h",
        "src_x", "src_y", "src_w", "src_h",
        "pivot_x", "pivot_y", "rotated", "boxes", "pivot_authored",
    )

    def __init__(
        self,
        name: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        src_x: int = 0,
        src_y: int = 0,
        src_w: int = 0,
        src_h: int = 0,
        pivot_x: float = 0.5,
        pivot_y: float = 0.5,
        rotated: bool = False,
        boxes: Tuple[Tuple[float, float, float, float], ...] = (),
        pivot_authored: bool = False,
    ):
        self.name = name
        self.x = int(x)
        self.y = int(y)
        self.w = max(1, int(w))
        self.h = max(1, int(h))
        self.src_x = float(src_x)
        self.src_y = float(src_y)
        sw = int(src_w) if src_w else (self.h if rotated else self.w)
        sh = int(src_h) if src_h else (self.w if rotated else self.h)
        self.src_w = max(1, sw)
        self.src_h = max(1, sh)
        self.pivot_x = float(pivot_x)
        self.pivot_y = float(pivot_y)
        self.rotated = bool(rotated)
        self.boxes = boxes
        # True when the atlas file named a pivot. A Sheet ``anchor=`` fills the
        # pivot of every other cell; an authored one wins.
        self.pivot_authored = bool(pivot_authored)

    def with_pivot(self, pivot_x: float, pivot_y: float) -> "AtlasFrame":
        """Same packed cell, another registration point (a per-Sheet view).

        Atlas frames are cached and shared between Sheets, so a Sheet never
        mutates one — it keeps its own copies with the resolved pivot.
        """
        return AtlasFrame(
            self.name, self.x, self.y, self.w, self.h,
            src_x=self.src_x, src_y=self.src_y,
            src_w=self.src_w, src_h=self.src_h,
            pivot_x=pivot_x, pivot_y=pivot_y,
            rotated=self.rotated, boxes=self.boxes,
            pivot_authored=self.pivot_authored,
        )

    def packed_rect(self) -> skia.Rect:
        return skia.Rect.MakeXYWH(float(self.x), float(self.y), float(self.w), float(self.h))


class AutoCollider:
    """Baked auto-hitbox in source pixel space (y-down, origin top-left of sourceSize)."""

    __slots__ = (
        "kind", "circle", "circles", "ellipse", "ellipses",
        "poly", "boxes", "precision", "recall",
    )

    def __init__(
        self,
        *,
        kind: str = "none",
        circle: Optional[Tuple[float, float, float]] = None,
        circles: Tuple[Tuple[float, float, float], ...] = (),
        ellipse: Optional[Tuple[float, float, float, float, float]] = None,
        ellipses: Tuple[Tuple[float, float, float, float, float], ...] = (),
        poly: Tuple[Tuple[float, float], ...] = (),
        boxes: Tuple[Tuple[float, float, float, float], ...] = (),
        precision: float = 0.0,
        recall: float = 0.0,
    ):
        self.kind = str(kind)
        self.circle = circle  # (cx, cy, r) or None — single-circle pick
        self.circles = circles  # 1+ circles when kind is "circles" (or a 1-tuple)
        self.ellipse = ellipse  # (cx, cy, rx, ry, angle_rad) or None — single
        self.ellipses = ellipses  # 2+ when kind is "ellipses"
        self.poly = poly  # source-space verts, y-down
        self.boxes = boxes
        self.precision = float(precision)
        self.recall = float(recall)

    def __bool__(self) -> bool:
        return self.kind not in ("", "none") and (
            self.circle is not None
            or bool(self.circles)
            or self.ellipse is not None
            or bool(self.ellipses)
            or bool(self.poly)
            or bool(self.boxes)
        )


# Tokens of live sheets. Their bakes stay until the sheet is released (bounded
# by its frame count); only bakes of unregistered images share the LRU cap
# (PA1: a 200-cell "each" sheet re-fitted every frame advance under one
# global cap of 128).
_SHEET_TOKENS: set = set()


def _key_tokens(key) -> Tuple[Any, ...]:
    """The image tokens a cache key names (a union key names one per frame)."""
    if not key:
        return ()
    head = key[0]
    if isinstance(head, tuple):
        return tuple(sig[0] for sig in head if sig)
    return (head,)


def reset_atlas_caches() -> None:
    _SHEET_TOKENS.clear()
    _AUTO_CACHE.clear()
    _MASK_CACHE.clear()
    _UNION_CACHE.clear()
    _FRAME_FX_CACHE.clear()
    _ATLAS_CACHE.clear()
    _IMAGE_TOKEN.clear()
    _IMAGE_HOLDERS.clear()


def alloc_sheet_token() -> int:
    """Monotonic id for one ``Sheet``. Cache keys use this, not ``id(image)``."""
    global _SHEET_TOKEN
    _SHEET_TOKEN += 1
    return _SHEET_TOKEN


def bind_sheet_images(token: int, images: Sequence[Any]) -> None:
    """Remember which live images belong to ``token`` so lookups find it.

    An image already bound by another live sheet keeps that sheet's token, so a
    second ``Sheet`` over the same decoded image reuses its bakes.
    """
    for image in images:
        if image is None:
            continue
        img_id = id(image)
        _IMAGE_HOLDERS.setdefault(img_id, set()).add(token)
        _IMAGE_TOKEN.setdefault(img_id, token)
        _SHEET_TOKENS.add(_IMAGE_TOKEN[img_id])


def _drop_cache_token(token: int) -> None:
    _SHEET_TOKENS.discard(token)
    for cache in (_AUTO_CACHE, _MASK_CACHE, _FRAME_FX_CACHE, _UNION_CACHE):
        dead = [key for key in cache if token in _key_tokens(key)]
        for key in dead:
            cache.pop(key, None)


def release_sheet_token(token: int) -> None:
    """Drop a dead sheet's hold on its images; purge bakes nobody holds."""
    orphaned = {token}
    for img_id in [i for i, held in _IMAGE_HOLDERS.items() if token in held]:
        held = _IMAGE_HOLDERS[img_id]
        held.discard(token)
        if held:
            continue
        del _IMAGE_HOLDERS[img_id]
        orphaned.add(_IMAGE_TOKEN.pop(img_id, token))
    live = set(_IMAGE_TOKEN.values())
    for tok in orphaned - live:
        _drop_cache_token(tok)


def image_cache_token(image: Any) -> int:
    """Sheet token for ``image``, or ``id(image)`` when no sheet registered it."""
    if image is None:
        return 0
    return _IMAGE_TOKEN.get(id(image), id(image))


def _cache_get(cache: "OrderedDict", key: Tuple[Any, ...]):
    hit = cache.get(key)
    if hit is None:
        return None
    cache.move_to_end(key)
    return hit


def _cache_put(cache: "OrderedDict", key: Tuple[Any, ...], value) -> None:
    cache[key] = value
    cache.move_to_end(key)
    if len(cache) <= _ATLAS_CACHE_CAP:
        return
    # Evict only bakes no live sheet holds (oldest first); a sheet's own bakes
    # leave with the sheet (``_drop_cache_token``). Runs on a bake (rare, ms).
    loose = [k for k in cache if not any(t in _SHEET_TOKENS for t in _key_tokens(k))]
    for k in loose[: max(0, len(loose) - _ATLAS_CACHE_CAP)]:
        cache.pop(k, None)


def _positive_trim(value, default: int = 0) -> int:
    """Starling ``frameX``/``frameY`` are often negative; spriteSourceSize is not.

    The blit treats ``src_x``/``src_y`` as a positive inset, same as
    TexturePacker's ``spriteSourceSize``. A negative trim is that inset with
    the opposite sign. A positive value is already the inset.
    """
    n = _as_int(value, default)
    if n < 0:
        return -n
    return n


def _as_int(value, default: int = 0) -> int:
    if value is None or value is False:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return bool(value)


def _xywh_from_mapping(obj: Any) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(obj, dict):
        return None
    if "frame" in obj and isinstance(obj["frame"], dict):
        return _xywh_from_mapping(obj["frame"])
    x = obj.get("x", obj.get("left"))
    y = obj.get("y", obj.get("top"))
    w = obj.get("w", obj.get("width"))
    h = obj.get("h", obj.get("height"))
    if x is None or y is None or w is None or h is None:
        return None
    return (_as_int(x), _as_int(y), max(1, _as_int(w, 1)), max(1, _as_int(h, 1)))


def _size_from_mapping(obj: Any) -> Optional[Tuple[int, int]]:
    if not isinstance(obj, dict):
        return None
    w = obj.get("w", obj.get("width"))
    h = obj.get("h", obj.get("height"))
    if w is None or h is None:
        return None
    return (max(1, _as_int(w, 1)), max(1, _as_int(h, 1)))


_PIVOT_KEYS = ("pivot", "anchor", "origin", "pivotX", "pivot_x", "pivotY", "pivot_y")


def _has_authored_pivot(obj: Any) -> bool:
    """The atlas entry names a pivot (the artist's registration point)."""
    return isinstance(obj, dict) and any(k in obj for k in _PIVOT_KEYS)


def _pivot_from_mapping(obj: Any, src_w: int, src_h: int) -> Tuple[float, float]:
    """Return normalized (0–1) pivot. Pixel values (>1) are divided by source size."""
    px, py = 0.5, 0.5
    if not isinstance(obj, dict):
        return px, py
    raw = obj.get("pivot", obj.get("anchor", obj.get("origin")))
    if isinstance(raw, dict):
        px = _as_float(raw.get("x", px), px)
        py = _as_float(raw.get("y", py), py)
    elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
        px = _as_float(raw[0], px)
        py = _as_float(raw[1], py)
    else:
        if "pivotX" in obj or "pivot_x" in obj:
            px = _as_float(obj.get("pivotX", obj.get("pivot_x")), px)
        if "pivotY" in obj or "pivot_y" in obj:
            py = _as_float(obj.get("pivotY", obj.get("pivot_y")), py)
    if abs(px) > 1.0 or abs(py) > 1.0:
        px = px / float(src_w) if src_w else 0.5
        py = py / float(src_h) if src_h else 0.5
    if not math.isfinite(px):
        px = 0.5
    if not math.isfinite(py):
        py = 0.5
    return px, py


def _boxes_from_mapping(obj: Any) -> Tuple[Tuple[float, float, float, float], ...]:
    if not isinstance(obj, dict):
        return ()
    raw = None
    for key in ("hitboxes", "hitBoxes", "boxes", "collision", "colliders"):
        if key in obj:
            raw = obj[key]
            break
    if raw is None:
        return ()
    out: List[Tuple[float, float, float, float]] = []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return ()
    for item in raw:
        if isinstance(item, dict):
            xywh = _xywh_from_mapping(item)
            if xywh is not None:
                out.append((float(xywh[0]), float(xywh[1]), float(xywh[2]), float(xywh[3])))
        elif isinstance(item, (list, tuple)) and len(item) >= 4:
            out.append((float(item[0]), float(item[1]), float(item[2]), float(item[3])))
    return tuple(out)


def _frame_from_json_entry(name: str, entry: Any) -> AtlasFrame:
    if not isinstance(entry, dict):
        raise ValueError(
            f"Atlas frame {name!r} expected an object with x/y/w/h (or frame={{...}}), "
            f"got {type(entry).__name__}."
        )
    xywh = _xywh_from_mapping(entry)
    if xywh is None:
        raise ValueError(
            f"Atlas frame {name!r} is missing x/y/width/height (or frame.x/y/w/h). "
            'Write {"x": 0, "y": 0, "w": 32, "h": 32}.'
        )
    x, y, w, h = xywh
    rotated = _as_bool(entry.get("rotated", False))
    src_x = src_y = 0
    src_w, src_h = (h, w) if rotated else (w, h)
    sss = entry.get("spriteSourceSize") or entry.get("sprite_source_size")
    if isinstance(sss, dict):
        src_x = _positive_trim(sss.get("x"), 0)
        src_y = _positive_trim(sss.get("y"), 0)
        if sss.get("w") is not None or sss.get("width") is not None:
            src_w = max(1, _as_int(sss.get("w", sss.get("width")), src_w))
            src_h = max(1, _as_int(sss.get("h", sss.get("height")), src_h))
    ss = entry.get("sourceSize") or entry.get("source_size")
    size = _size_from_mapping(ss) if isinstance(ss, dict) else None
    if size is not None:
        src_w, src_h = size
    # Kenney / XML-style trim on the same object.
    if "frameX" in entry or "frameWidth" in entry:
        src_x = _positive_trim(entry.get("frameX"), src_x)
        src_y = _positive_trim(entry.get("frameY"), src_y)
        fw = entry.get("frameWidth")
        fh = entry.get("frameHeight")
        if fw is not None:
            src_w = max(1, _as_int(fw, src_w))
        if fh is not None:
            src_h = max(1, _as_int(fh, src_h))
    px, py = _pivot_from_mapping(entry, src_w, src_h)
    boxes = _boxes_from_mapping(entry)
    return AtlasFrame(
        name, x, y, w, h,
        src_x=src_x, src_y=src_y, src_w=src_w, src_h=src_h,
        pivot_x=px, pivot_y=py, rotated=rotated, boxes=boxes,
        pivot_authored=_has_authored_pivot(entry),
    )


def parse_atlas_json(path: str) -> Tuple[Optional[str], Tuple[AtlasFrame, ...]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Atlas JSON {path!r} is not valid JSON ({e}). "
                "TexturePacker Hash/Array and a simple {frames: {name: {x,y,w,h}}} both work."
            ) from e
        except UnicodeDecodeError:
            # A binary or non-UTF-8 file leaked Python's codec error (PA8).
            raise ValueError(
                f"Atlas file {path!r} is not UTF-8 text: an atlas is a JSON or XML file. "
                "Did you pass the image as atlas=?"
            ) from None
    if not isinstance(data, dict):
        raise ValueError(
            f"Atlas JSON {path!r} expected an object, got {type(data).__name__}."
        )
    image = None
    meta = data.get("meta")
    if isinstance(meta, dict):
        image = meta.get("image") or meta.get("imagePath")
    image = image or data.get("image") or data.get("imagePath")
    if image is not None:
        image = str(image)

    raw_frames = data.get("frames", data.get("textures", data.get("sprites")))
    if raw_frames is None and all(k in data for k in ("x", "y")) is False:
        # Whole file is the frames dict (no wrapper).
        skip = {"meta", "image", "imagePath", "format", "size", "scale"}
        if any(isinstance(v, dict) and ("x" in v or "frame" in v) for k, v in data.items() if k not in skip):
            raw_frames = {k: v for k, v in data.items() if k not in skip}

    frames: List[AtlasFrame] = []
    if isinstance(raw_frames, dict):
        for name, entry in raw_frames.items():
            frames.append(_frame_from_json_entry(str(name), entry))
    elif isinstance(raw_frames, list):
        for i, entry in enumerate(raw_frames):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Atlas JSON {path!r} frames[{i}] expected an object, "
                    f"got {type(entry).__name__}."
                )
            name = entry.get("filename") or entry.get("name") or str(i)
            frames.append(_frame_from_json_entry(str(name), entry))
    else:
        raise ValueError(
            f"Atlas JSON {path!r} needs a \"frames\" object or array. "
            'Example: {"frames": {"shipOn": {"x": 0, "y": 0, "w": 64, "h": 64}}}.'
        )
    if not frames:
        raise ValueError(f"Atlas JSON {path!r} has no frames.")
    return image, tuple(frames)


def parse_atlas_xml(path: str) -> Tuple[Optional[str], Tuple[AtlasFrame, ...]]:
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError as e:
        raise ValueError(
            f"Atlas XML {path!r} is not valid XML ({e}). "
            "Kenney / TexturePacker TextureAtlas with SubTexture children is supported."
        ) from e
    image = root.get("imagePath") or root.get("image") or root.get("imagepath")
    frames: List[AtlasFrame] = []
    for el in root.iter():
        tag = (el.tag or "").split("}")[-1].lower()
        if tag not in ("subtexture", "sprite", "texture"):
            continue
        name = el.get("name") or el.get("n") or f"frame{len(frames)}"
        x = _as_int(el.get("x"), 0)
        y = _as_int(el.get("y"), 0)
        w = _as_int(el.get("width", el.get("w")), 0)
        h = _as_int(el.get("height", el.get("h")), 0)
        if w <= 0 or h <= 0:
            continue
        rotated = _as_bool(el.get("rotated", False))
        src_x = _positive_trim(el.get("frameX"), 0)
        src_y = _positive_trim(el.get("frameY"), 0)
        src_w = _as_int(el.get("frameWidth"), 0)
        src_h = _as_int(el.get("frameHeight"), 0)
        px = el.get("pivotX", el.get("pivot_x"))
        py = el.get("pivotY", el.get("pivot_y"))
        sw = src_w or (h if rotated else w)
        sh = src_h or (w if rotated else h)
        pivot_x, pivot_y = 0.5, 0.5
        if px is not None or py is not None:
            pivot_x = _as_float(px, 0.5)
            pivot_y = _as_float(py, 0.5)
            dummy = {"pivotX": pivot_x, "pivotY": pivot_y}
            pivot_x, pivot_y = _pivot_from_mapping(dummy, sw, sh)
        boxes = ()
        # Nested <hitbox x= y= width= height= /> children, if present.
        kids = []
        for child in list(el):
            ctag = (child.tag or "").split("}")[-1].lower()
            if ctag in ("hitbox", "box", "collider"):
                kids.append({
                    "x": child.get("x"), "y": child.get("y"),
                    "w": child.get("width", child.get("w")),
                    "h": child.get("height", child.get("h")),
                })
        if kids:
            boxes = _boxes_from_mapping({"hitboxes": kids})
        frames.append(AtlasFrame(
            str(name), x, y, w, h,
            src_x=src_x, src_y=src_y, src_w=src_w, src_h=src_h,
            pivot_x=pivot_x, pivot_y=pivot_y, rotated=rotated, boxes=boxes,
            pivot_authored=px is not None or py is not None,
        ))
    # The recursive findall can duplicate the direct children — unique by (name,x,y).
    seen = set()
    uniq: List[AtlasFrame] = []
    for fr in frames:
        key = (fr.name, fr.x, fr.y, fr.w, fr.h)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(fr)
    if not uniq:
        raise ValueError(
            f"Atlas XML {path!r} has no SubTexture / sprite entries. "
            'Expected <TextureAtlas><SubTexture name="…" x="…" y="…" width="…" height="…"/>.'
        )
    return (str(image) if image else None), tuple(uniq)


def load_atlas(path: str) -> Tuple[Optional[str], Tuple[AtlasFrame, ...]]:
    """Parse JSON or XML atlas. Cached per absolute path."""
    key = os.path.abspath(path)
    hit = _ATLAS_CACHE.get(key)
    if hit is not None:
        return hit
    ext = os.path.splitext(key)[1].lower()
    if ext == ".xml":
        result = parse_atlas_xml(key)
    elif ext in (".json", ".atlas"):
        result = parse_atlas_json(key)
    else:
        # Peek: XML vs JSON.
        with open(key, "rb") as f:
            start = f.read(64).lstrip().decode("utf-8", "replace")
        if start.startswith("<"):
            result = parse_atlas_xml(key)
        else:
            result = parse_atlas_json(key)
    _ATLAS_CACHE[key] = result
    return result


def is_atlas_filename(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    ext = os.path.splitext(name)[1].lower()
    return ext in (".json", ".xml", ".atlas")


def _largest_rect(occupied: np.ndarray) -> Optional[Tuple[int, int, int, int, int]]:
    """Largest all-True axis-aligned rectangle in ``occupied``.

    Classic "largest rectangle in a binary matrix": build a per-column
    histogram of consecutive True cells ending at each row, then solve
    "largest rectangle in histogram" (monotonic stack) per row. Returns
    ``(x, y, w, h, area)`` or None if ``occupied`` is all False.
    """
    h, w = occupied.shape
    heights = np.zeros(w, dtype=np.int64)
    best: Optional[Tuple[int, int, int, int, int]] = None
    best_area = 0
    for y in range(h):
        row = occupied[y]
        heights = np.where(row, heights + 1, 0)
        stack: List[int] = []
        for x in range(w + 1):
            cur = int(heights[x]) if x < w else 0
            while stack and heights[stack[-1]] >= cur:
                top = stack.pop()
                height = int(heights[top])
                left = stack[-1] + 1 if stack else 0
                width = x - left
                area = height * width
                if area > best_area:
                    best_area = area
                    best = (left, y - height + 1, width, height, area)
            stack.append(x)
    return best


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill enclosed transparent pockets (border flood-fill on background).

    Open notches / concave corners that connect to the mask edge stay empty.
    """
    if mask.size == 0:
        return mask
    h, w = mask.shape
    bg = ~mask
    reached = np.zeros_like(bg, dtype=bool)
    q: deque = deque()
    for x in range(w):
        for y in (0, h - 1):
            if bg[y, x] and not reached[y, x]:
                reached[y, x] = True
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if bg[y, x] and not reached[y, x]:
                reached[y, x] = True
                q.append((x, y))
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and bg[ny, nx] and not reached[ny, nx]:
                reached[ny, nx] = True
                q.append((nx, ny))
    holes = bg & ~reached
    if not holes.any():
        return mask
    return mask | holes


def _trimmed_centroid(
    xs: np.ndarray, ys: np.ndarray, *, percentile: float = 85.0,
) -> Tuple[float, float]:
    cx0, cy0 = float(xs.mean()), float(ys.mean())
    d0 = np.hypot(xs - cx0, ys - cy0)
    core = d0 <= np.percentile(d0, percentile)
    if not core.any():
        core = np.ones_like(d0, dtype=bool)
    return float(xs[core].mean()), float(ys[core].mean())


def _shape_metrics(
    mask: np.ndarray, inside: np.ndarray, *, area: Optional[float] = None,
) -> Tuple[float, float]:
    """Return (precision, recall) for ``inside`` vs opaque ``mask``.

    ``area`` is the shape's true geometric area (e.g. ``pi * r * r`` for a
    circle). It defaults to the in-bounds grid-cell count, which is only
    correct when the shape can never extend past the mask's own bounds
    (true for hull/rect candidates, built from mask geometry). Circle and
    ellipse fits *can* extend past the mask — a thin, tall sprite (e.g. a
    laser bolt) can need a radius wider than its own frame — and scoring
    precision against the clipped grid instead of the real area hides that
    overshoot entirely (every "extra" pixel is off-canvas, so it's absent
    from the array and never counted against precision), letting a wildly
    oversized circle report a false 100% precision.
    """
    total = int(mask.sum())
    if total <= 0:
        return 0.0, 0.0
    grid_in = int(inside.sum())
    if grid_in <= 0:
        return 0.0, 0.0
    true_area = float(area) if area is not None else float(grid_in)
    if true_area <= 0:
        return 0.0, 0.0
    opaque_in = int(np.count_nonzero(mask & inside))
    # Discrete pixel centers can outnumber analytic area for small disks;
    # clamp so precision never exceeds 1 (and quality never exceeds 1).
    precision = min(1.0, opaque_in / true_area)
    recall = opaque_in / total
    return precision, recall


def fit_circle(
    mask: np.ndarray,
    *,
    min_precision: float = _AUTO_PRECISION_MIN,
    best_effort: bool = False,
) -> Optional[Tuple[float, float, float, float, float]]:
    """Best precision-capped circle: (cx, cy, r, precision, recall) or None.

    When ``best_effort`` (lab ``force_kind="circle"``), if nothing clears
    ``min_precision``, return the candidate with the highest quality score
    instead of ``None`` — so the overlay never falls back to a full rect.
    """
    ys, xs = np.nonzero(mask)
    if xs.size < 8:
        return None
    cx, cy = _trimmed_centroid(xs, ys)
    total = int(mask.sum())
    if total <= 0:
        return None
    hh, ww = mask.shape
    yy = np.arange(hh, dtype=np.float64)[:, None]
    xx = np.arange(ww, dtype=np.float64)[None, :]
    dist2 = (xx - cx) * (xx - cx) + (yy - cy) * (yy - cy)
    d = np.hypot(xs - cx, ys - cy)
    candidates = {float(v) for v in np.percentile(d, (40, 50, 60, 70, 75, 80, 85, 90, 95, 100))}
    candidates.add(float(np.sqrt(total / math.pi)))
    best_rec = -1.0
    best: Optional[Tuple[float, float, float, float, float]] = None
    best_q = -1.0
    best_any: Optional[Tuple[float, float, float, float, float]] = None
    for r in sorted(candidates):
        if not math.isfinite(r) or r < 1.0:
            continue
        inside = dist2 <= r * r
        prec, rec = _shape_metrics(mask, inside, area=math.pi * r * r)
        cand = (cx, cy, r, prec, rec)
        q = _quality_score(prec, rec)
        if q > best_q:
            best_q = q
            best_any = cand
        if prec >= min_precision and rec > best_rec:
            best_rec = rec
            best = cand
    if best is not None:
        return best
    return best_any if best_effort else None


def fit_ellipse(
    mask: np.ndarray,
    *,
    min_precision: float = _AUTO_PRECISION_MIN,
    best_effort: bool = False,
) -> Optional[Tuple[float, float, float, float, float, float, float]]:
    """Best precision-capped ellipse: (cx, cy, rx, ry, ang, precision, recall) or None.

    ``best_effort`` (lab force) keeps a quality-maximizing ellipse when the
    precision floor cannot be met — same contract as ``fit_circle``.
    """
    ys, xs = np.nonzero(mask)
    if xs.size < 8:
        return None
    cx, cy = _trimmed_centroid(xs, ys)
    dx = xs.astype(np.float64) - cx
    dy = ys.astype(np.float64) - cy
    d0 = np.hypot(dx, dy)
    core = d0 <= np.percentile(d0, 85)
    if not core.any():
        core = np.ones_like(d0, dtype=bool)
    cov = np.cov(np.stack([dx[core], dy[core]]))
    evals, evecs = np.linalg.eigh(cov)
    ang = math.atan2(float(evecs[1, -1]), float(evecs[0, -1]))
    c, s = math.cos(ang), math.sin(ang)
    u = dx * c + dy * s
    v = -dx * s + dy * c
    hh, ww = mask.shape
    yy = np.arange(hh, dtype=np.float64)[:, None]
    xx = np.arange(ww, dtype=np.float64)[None, :]
    ddx, ddy = xx - cx, yy - cy
    uu = ddx * c + ddy * s
    vv = -ddx * s + ddy * c
    ru_cands = np.percentile(np.abs(u), (50, 60, 70, 75, 80, 85, 90, 95, 100))
    rv_cands = np.percentile(np.abs(v), (50, 60, 70, 75, 80, 85, 90, 95, 100))
    best_rec = -1.0
    best: Optional[Tuple[float, float, float, float, float, float, float]] = None
    best_q = -1.0
    best_any: Optional[Tuple[float, float, float, float, float, float, float]] = None
    for ru in ru_cands:
        if ru < 1.0:
            continue
        for rv in rv_cands:
            if rv < 1.0:
                continue
            inside = _sq(uu / ru) + _sq(vv / rv) <= 1.0
            prec, rec = _shape_metrics(mask, inside, area=math.pi * ru * rv)
            cand = (cx, cy, float(ru), float(rv), ang, prec, rec)
            q = _quality_score(prec, rec)
            if q > best_q:
                best_q = q
                best_any = cand
            if prec >= min_precision and rec > best_rec:
                best_rec = rec
                best = cand
    if best is not None:
        return best
    return best_any if best_effort else None


def _ellipse_inside_grid(
    hh: int, ww: int,
    cx: float, cy: float, rx: float, ry: float, ang: float,
) -> np.ndarray:
    yy = np.arange(hh, dtype=np.float64)[:, None]
    xx = np.arange(ww, dtype=np.float64)[None, :]
    c, s = math.cos(ang), math.sin(ang)
    ddx, ddy = xx - cx, yy - cy
    uu = ddx * c + ddy * s
    vv = -ddx * s + ddy * c
    return _sq(uu / rx) + _sq(vv / ry) <= 1.0


def _score_two_ellipses(
    mask: np.ndarray,
    e1: Tuple[float, float, float, float, float],
    e2: Tuple[float, float, float, float, float],
) -> Optional[Tuple[float, float]]:
    """Return ``(precision, recall)`` for the union of two ellipses, or None."""
    hh, ww = mask.shape
    inside1 = _ellipse_inside_grid(hh, ww, *e1)
    inside2 = _ellipse_inside_grid(hh, ww, *e2)
    inside = inside1 | inside2
    grid_in = int(inside.sum())
    if grid_in <= 0:
        return None
    area1 = math.pi * e1[2] * e1[3]
    area2 = math.pi * e2[2] * e2[3]
    overlap = int(np.count_nonzero(inside1 & inside2))
    # Σπr² double-counts the intersection; subtract grid overlap so precision
    # is not artificially crushed on plus/T centers (still penalizes off-mask
    # overshoot when analytic union exceeds the in-bounds grid).
    union_area = max(area1 + area2 - float(overlap), float(grid_in), 1.0)
    return _shape_metrics(mask, inside, area=union_area)


def fit_two_ellipses(
    mask: np.ndarray,
    *,
    min_precision: float = _AUTO_PRECISION_MIN,
    min_recall_gain: float = _AUTO_TWO_ELLIPSE_MIN_GAIN,
    strict: bool = True,
) -> Optional[Tuple[
    Tuple[Tuple[float, float, float, float, float], Tuple[float, float, float, float, float]],
    float,
    float,
]]:
    """Two ellipses for T / plus / X / multi-lobe silhouettes.

    Strategies (best recall wins):
      1. Axis-aligned H+V arm split (plus / T)
      2. Diagonal nearest-line split (X / ×)
      3. Residual after the single best ellipse

    When ``strict`` (auto policy), the pair must clear precision, beat the
    single-ellipse recall by ``min_recall_gain``, and reach
    ``_AUTO_TWO_ELLIPSE_MIN_RECALL``. Lab ``force_kind="ellipses"`` passes
    ``strict=False`` so any valid pair is returned for inspection.
    """
    total = int(mask.sum())
    if total < 16:
        return None

    # Forced / lab: allow slightly looser arm fits so more shapes produce a pair.
    arm_precision = float(min_precision) if strict else min(float(min_precision), 0.75)
    # Diagonal arms are thick relative to a thin ellipse; 0.90 per-arm often
    # yields needle ellipses. Union precision still has to clear the strict bar.
    diag_precision = min(arm_precision, 0.80)

    single = fit_ellipse(mask, min_precision=arm_precision)
    rec1 = float(single[6]) if single is not None else 0.0
    best: Optional[Tuple[
        Tuple[Tuple[float, float, float, float, float], Tuple[float, float, float, float, float]],
        float,
        float,
    ]] = None

    def _consider(
        ea: Tuple[float, float, float, float, float],
        eb: Tuple[float, float, float, float, float],
    ) -> None:
        nonlocal best
        # Reject near-duplicate pairs (two almost-identical central blobs).
        if _ellipses_redundant(ea, eb):
            return
        scored = _score_two_ellipses(mask, ea, eb)
        if scored is None:
            return
        prec, rec = scored
        if strict:
            if prec < min_precision:
                return
            if rec < rec1 + float(min_recall_gain):
                return
            if rec < _AUTO_TWO_ELLIPSE_MIN_RECALL:
                return
        elif prec <= 0.0 or rec <= 0.0:
            return
        if best is None or rec > best[2] or (rec == best[2] and prec > best[1]):
            best = ((ea, eb), prec, rec)

    # --- Horizontal + vertical arms (plus / T) ---
    row_dens = mask.sum(axis=1).astype(np.float64)
    col_dens = mask.sum(axis=0).astype(np.float64)
    rmax = float(row_dens.max()) if row_dens.size else 0.0
    cmax = float(col_dens.max()) if col_dens.size else 0.0
    if rmax > 0.0 and cmax > 0.0:
        h_arm = mask & (row_dens >= 0.45 * rmax)[:, None]
        v_arm = mask & (col_dens >= 0.45 * cmax)[None, :]
        only_h = int(np.count_nonzero(h_arm & ~v_arm))
        only_v = int(np.count_nonzero(v_arm & ~h_arm))
        if only_h >= 4 and only_v >= 4 and int(h_arm.sum()) >= 8 and int(v_arm.sum()) >= 8:
            e_h = fit_ellipse(h_arm, min_precision=arm_precision)
            e_v = fit_ellipse(v_arm, min_precision=arm_precision)
            if e_h is not None and e_v is not None:
                _consider(e_h[:5], e_v[:5])

    # --- Diagonal arms (X / ×): assign each opaque pixel to the nearer of
    # the two 45° diagonals through the centroid. ---
    ys, xs = np.nonzero(mask)
    if xs.size >= 16:
        cx_m = float(xs.mean())
        cy_m = float(ys.mean())
        # | (x-cx) - (y-cy) |  → distance to slope +1;  | (x-cx)+(y-cy) | → slope −1
        d_pos = np.abs((xs.astype(np.float64) - cx_m) - (ys.astype(np.float64) - cy_m))
        d_neg = np.abs((xs.astype(np.float64) - cx_m) + (ys.astype(np.float64) - cy_m))
        arm_pos = np.zeros_like(mask)
        arm_neg = np.zeros_like(mask)
        arm_pos[ys[d_pos <= d_neg], xs[d_pos <= d_neg]] = True
        arm_neg[ys[d_pos > d_neg], xs[d_pos > d_neg]] = True
        if int(arm_pos.sum()) >= 8 and int(arm_neg.sum()) >= 8:
            e_pos = fit_ellipse(arm_pos, min_precision=diag_precision)
            e_neg = fit_ellipse(arm_neg, min_precision=diag_precision)
            if e_pos is not None and e_neg is not None:
                _consider(e_pos[:5], e_neg[:5])

    # --- Residual after primary full-mask ellipse ---
    if single is not None:
        cx, cy, rx, ry, ang = single[:5]
        hh, ww = mask.shape
        inside1 = _ellipse_inside_grid(hh, ww, cx, cy, rx, ry, ang)
        residual = mask & ~inside1
        if int(residual.sum()) >= 8:
            second = fit_ellipse(residual, min_precision=arm_precision)
            if second is not None:
                _consider(single[:5], second[:5])

    return best


def _ellipses_redundant(
    ea: Tuple[float, float, float, float, float],
    eb: Tuple[float, float, float, float, float],
) -> bool:
    """True when two ellipses are nearly the same central blob (bad X fit)."""
    ax, ay, arx, ary, aang = ea
    bx, by, brx, bry, bang = eb
    # Centers almost coincide relative to size.
    scale = max(arx, ary, brx, bry, 1.0)
    if math.hypot(ax - bx, ay - by) > 0.35 * scale:
        return False
    # Both nearly round (aspect ≤ 1.35).
    def _aspect(rx: float, ry: float) -> float:
        lo = min(abs(rx), abs(ry))
        hi = max(abs(rx), abs(ry))
        return hi / max(lo, 1e-6)

    if _aspect(arx, ary) > 1.35 or _aspect(brx, bry) > 1.35:
        return False
    # Both nearly round: the fitted angle is noise, not a different blob.
    if (
        ellipse_as_circle(arx, ary) is not None
        and ellipse_as_circle(brx, bry) is not None
    ):
        return True
    # Orientation similar (mod 180°).
    diff = abs(math.degrees(aang - bang)) % 180.0
    diff = min(diff, 180.0 - diff)
    return diff < 35.0


def _cross(o: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _convex_hull(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) <= 2:
        return list(pts)
    lower: List[Tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: List[Tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _poly_area(poly: Sequence[Tuple[float, float]]) -> float:
    n = len(poly)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


def _triangle_area(
    a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float],
) -> float:
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) * 0.5


def _point_in_convex(
    px: float, py: float, poly: Sequence[Tuple[float, float]], eps: float = 1e-6,
) -> bool:
    """True when ``(px, py)`` is inside a CCW convex ring, boundary included."""
    n = len(poly)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        if cross < -eps:
            return False
    return True


def _occupied_centers(mask: np.ndarray) -> List[Tuple[float, float]]:
    ys, xs = np.nonzero(mask)
    return [(float(x) + 0.5, float(y) + 0.5) for x, y in zip(xs.tolist(), ys.tolist())]


def _simplify_hull(
    hull: List[Tuple[float, float]],
    centers: Sequence[Tuple[float, float]],
    *,
    max_verts: int,
) -> List[Tuple[float, float]]:
    """Drop the cheapest vertex that still covers every occupied cell.

    Cutting a corner to hit ``max_verts`` used to report recall 1 while
    leaving pixels outside. If no legal drop remains, keep the extra verts.

    Every centre starts inside the corner hull, and each accepted drop keeps
    that true, so a candidate only has to clear its new chord. A convex chord
    covers the centres exactly when it covers their hull, so the probe is that
    hull rather than every cell. Re-testing each cell against the whole trial
    polygon is cubic in the vertex count and stalls the frame on a round
    sprite (the first ``Sprite("ball.png")`` bake).
    """
    poly = list(hull)
    cap = max(3, int(max_verts))
    if len(poly) <= cap:
        return poly
    probe = _convex_hull(centers)
    eps = 1e-6
    while len(poly) > cap:
        n = len(poly)
        best_i = None
        best_cost = 1e300
        for i in range(n):
            ax, ay = poly[i - 1]
            bx, by = poly[(i + 1) % n]
            dx, dy = bx - ax, by - ay
            if any(dx * (py - ay) - dy * (px - ax) < -eps for px, py in probe):
                continue
            cost = _triangle_area(poly[i - 1], poly[i], poly[(i + 1) % n])
            if cost < best_cost:
                best_cost = cost
                best_i = i
        if best_i is None:
            break
        poly.pop(best_i)
    return poly


def _raster_hull_metrics(
    mask: np.ndarray, poly: Sequence[Tuple[float, float]],
) -> Tuple[float, float]:
    """Precision and recall from cells whose centres lie in ``poly``."""
    total = int(mask.sum())
    if total <= 0 or len(poly) < 3:
        return 0.0, 0.0
    mh, mw = mask.shape
    inside = 0
    hit = 0
    for y in range(mh):
        for x in range(mw):
            if not _point_in_convex(x + 0.5, y + 0.5, poly):
                continue
            inside += 1
            if mask[y, x]:
                hit += 1
    recall = hit / float(total)
    precision = (hit / float(inside)) if inside else 0.0
    return precision, recall


def fit_bbox(mask: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """Axis-aligned bounding box of occupied cells: ``(x, y, w, h)`` or ``None``.

    Recall is 1.0 by construction (every True cell is inside). Empty mask
    returns ``None``; a single pixel returns a 1×1 box.
    """
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    x0 = int(xs.min())
    x1 = int(xs.max())
    y0 = int(ys.min())
    y1 = int(ys.max())
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def fit_hull(
    mask: np.ndarray,
    *,
    max_verts: int = _AUTO_HULL_MAX_VERTS,
) -> Optional[Tuple[Tuple[Tuple[float, float], ...], float, float]]:
    """Convex hull of occupied cell corners, simplified without losing pixels.

    Returns ``(verts, precision, recall)``. Verts are in the same index space
    as before (the source mapper adds half a cell). Recall is the rasterized
    fraction of occupied centres inside the polygon, not a hardcoded 1.
    """
    ys, xs = np.nonzero(mask)
    if xs.size < 3:
        return None
    pts: List[Tuple[float, float]] = []
    for x, y in zip(xs.tolist(), ys.tolist()):
        xf, yf = float(x), float(y)
        pts.extend(((xf, yf), (xf + 1.0, yf), (xf + 1.0, yf + 1.0), (xf, yf + 1.0)))
    hull = _convex_hull(pts)
    if len(hull) < 3:
        return None
    centers = _occupied_centers(mask)
    hull = _simplify_hull(hull, centers, max_verts=max_verts)
    if len(hull) < 3:
        return None
    precision, recall = _raster_hull_metrics(mask, hull)
    if precision <= 0.0 and recall <= 0.0:
        return None
    # Mapper adds +0.5, so store corners shifted back by half a cell.
    verts = tuple((x - 0.5, y - 0.5) for x, y in hull)
    return verts, precision, recall


def greedy_rects(
    mask: np.ndarray,
    *,
    max_rects: Optional[int] = None,
    target: float = _AUTO_RECT_TARGET,
    diminish_floor: float = _AUTO_RECT_DIMINISH_FLOOR,
    min_gain: float = _AUTO_RECT_MIN_GAIN,
) -> List[Tuple[int, int, int, int]]:
    """Adaptive largest-rect cover. Stops at target coverage, diminishing gain, or cap."""
    if mask.size == 0 or not np.any(mask):
        return []
    cap = max(1, int(max_rects if max_rects is not None else _AUTO_RECT_CAP))
    occupied = np.array(mask, dtype=bool, copy=True)
    total = int(mask.sum())
    if total <= 0:
        return []
    bbox_area = float(mask.shape[0] * mask.shape[1])
    min_gain_px = max(1.0, min_gain * bbox_area)
    rects: List[Tuple[int, int, int, int]] = []
    covered = 0
    while len(rects) < cap:
        found = _largest_rect(occupied)
        if found is None or found[4] <= 0:
            break
        x, y, w, h, area = found
        cur_cov = covered / total
        if cur_cov >= diminish_floor and area < min_gain_px:
            break
        occupied[y:y + h, x:x + w] = False
        rects.append((x, y, w, h))
        covered += area
        if covered / total >= target:
            break
    return rects


def _rect_coverage(
    mask: np.ndarray, rects: Sequence[Tuple[int, int, int, int]],
) -> Tuple[float, float]:
    """Return (coverage/recall, precision) for tight rects (precision always 1).

    Only valid for non-overlapping, fully-opaque rects such as
    ``greedy_rects`` produces (each one comes straight off ``_largest_rect``,
    which never returns a region with a transparent cell in it). Don't reuse
    this for arbitrary/overlapping rects — it doesn't check overlap or
    verify opacity, so it would silently under-report overshoot.
    """
    total = int(mask.sum())
    if total <= 0 or not rects:
        return 0.0, 1.0
    covered = sum(w * h for _, _, w, h in rects)
    return min(1.0, covered / total), 1.0


def _distance_to_false(mask: np.ndarray) -> np.ndarray:
    """Euclidean distance from each True cell to the nearest False (padded)."""
    h, w = mask.shape
    padded = np.pad(mask, 1, constant_values=False)
    fy, fx = np.nonzero(~padded)
    py, px = np.nonzero(padded)
    dt_pad = np.zeros(padded.shape, dtype=np.float64)
    if py.size == 0:
        return dt_pad[1:-1, 1:-1]
    fy64 = fy.astype(np.float64)
    fx64 = fx.astype(np.float64)
    n = int(py.size)
    best = np.empty(n, dtype=np.float64)
    chunk = 256
    for i in range(0, n, chunk):
        ys = py[i:i + chunk].astype(np.float64)[:, None]
        xs = px[i:i + chunk].astype(np.float64)[:, None]
        d2 = (ys - fy64) * (ys - fy64) + (xs - fx64) * (xs - fx64)
        best[i:i + chunk] = np.sqrt(d2.min(axis=1))
    dt_pad[py, px] = best
    return dt_pad[1:-1, 1:-1]


def _largest_inscribed_circle(
    occupied: np.ndarray,
) -> Optional[Tuple[float, float, float]]:
    """Largest circle whose interior stays in ``True`` cells: ``(cx, cy, r)``."""
    if occupied.size == 0 or not np.any(occupied):
        return None
    dt = _distance_to_false(occupied)
    idx = int(np.argmax(dt))
    cy_i, cx_i = divmod(idx, dt.shape[1])
    r_hit = float(dt[cy_i, cx_i])
    # Distance is to the nearest False *center*; shrink a half-pixel so the
    # disk does not include that empty cell.
    r = r_hit - 0.5
    if not math.isfinite(r) or r < 1.0:
        return None
    return float(cx_i), float(cy_i), r


def greedy_circles(
    mask: np.ndarray,
    *,
    max_circles: Optional[int] = None,
    target: float = _AUTO_RECT_TARGET,
    diminish_floor: float = _AUTO_RECT_DIMINISH_FLOOR,
    min_gain: float = _AUTO_RECT_MIN_GAIN,
) -> List[Tuple[float, float, float]]:
    """Adaptive largest-inscribed-circle cover. Analogous to ``greedy_rects``."""
    if mask.size == 0 or not np.any(mask):
        return []
    cap = max(1, int(max_circles if max_circles is not None else _AUTO_CIRCLE_CAP))
    occupied = np.array(mask, dtype=bool, copy=True)
    total = int(mask.sum())
    if total <= 0:
        return []
    bbox_area = float(mask.shape[0] * mask.shape[1])
    min_gain_px = max(1.0, min_gain * bbox_area)
    hh, ww = occupied.shape
    yy = np.arange(hh, dtype=np.float64)[:, None]
    xx = np.arange(ww, dtype=np.float64)[None, :]
    circles: List[Tuple[float, float, float]] = []
    covered = 0
    while len(circles) < cap:
        found = _largest_inscribed_circle(occupied)
        if found is None:
            break
        cx, cy, r = found
        area = math.pi * r * r
        cur_cov = covered / total
        if cur_cov >= diminish_floor and area < min_gain_px:
            break
        inside = (xx - cx) * (xx - cx) + (yy - cy) * (yy - cy) <= r * r
        gained = int(np.count_nonzero(occupied & inside))
        if gained <= 0:
            break
        occupied[inside] = False
        circles.append((cx, cy, r))
        covered += gained
        if covered / total >= target:
            break
    return circles


def _circle_coverage(
    mask: np.ndarray, circles: Sequence[Tuple[float, float, float]],
) -> Tuple[float, float]:
    """Return (precision, recall) for a set of disks vs ``mask``."""
    if mask.size == 0 or not circles:
        return 0.0, 0.0
    hh, ww = mask.shape
    yy = np.arange(hh, dtype=np.float64)[:, None]
    xx = np.arange(ww, dtype=np.float64)[None, :]
    inside = np.zeros_like(mask, dtype=bool)
    area = 0.0
    for cx, cy, r in circles:
        if r <= 0.0:
            continue
        inside |= (xx - cx) * (xx - cx) + (yy - cy) * (yy - cy) <= r * r
        area += math.pi * r * r
    return _shape_metrics(mask, inside, area=area)


def _quality_score(precision: float, recall: float) -> float:
    """Precision-weighted quality in ``[0, 1]``.

    Precision is raised to ``_AUTO_PRECISION_EXP`` (1.5): overshoot is
    penalized more than linearly. Recall only needs to reach the quality
    bar — extra recall above it buys nothing, so a cheaper/tighter
    candidate sitting right at the bar can still beat a bigger one that
    "fully" covers the sprite by bridging concave gaps with excess area.
    """
    precision = min(1.0, max(0.0, float(precision)))
    recall = max(0.0, float(recall))
    if precision <= 0.0 or recall <= 0.0:
        return 0.0
    rec_term = min(1.0, recall / _AUTO_QUALITY_BAR)
    return (precision ** _AUTO_PRECISION_EXP) * rec_term


def _hull_quality(precision: float, recall: float) -> float:
    """Quality for a convex hull, with an extra concavity (overshoot) guard."""
    q = _quality_score(precision, recall)
    precision = min(1.0, max(0.0, float(precision)))
    if precision < _AUTO_HULL_PRECISION_GUARD:
        q *= precision / _AUTO_HULL_PRECISION_GUARD
    return q


def _utility(quality: float, cost: float, *, lam: float = _AUTO_COST_LAMBDA) -> float:
    return float(quality) - float(lam) * float(cost)


def _rect_runtime_cost(n: int) -> float:
    """Auto assumes sprites may rotate → rects cost as OBBs."""
    return _AUTO_COST_OBB * max(0, int(n))


def _hull_runtime_cost(nverts: int) -> float:
    return _AUTO_COST_HULL + _AUTO_COST_HULL_PER_VERT * max(0, int(nverts) - 4)


def _boxes_collider(rects: Sequence[Tuple[int, int, int, int]], prec: float, rec: float) -> AutoCollider:
    return AutoCollider(
        kind="boxes",
        boxes=tuple((float(x), float(y), float(w), float(h)) for x, y, w, h in rects),
        precision=prec,
        recall=rec,
    )


def _circles_collider(
    circles: Sequence[Tuple[float, float, float]], prec: float, rec: float,
) -> AutoCollider:
    seq = tuple((float(cx), float(cy), float(r)) for cx, cy, r in circles)
    if len(seq) == 1:
        return AutoCollider(
            kind="circle", circle=seq[0], circles=seq, precision=prec, recall=rec,
        )
    return AutoCollider(kind="circles", circles=seq, precision=prec, recall=rec)


def _ellipses_collider(
    ellipses: Sequence[Tuple[float, float, float, float, float]],
    prec: float,
    rec: float,
) -> AutoCollider:
    seq = tuple(
        (float(cx), float(cy), float(rx), float(ry), float(ang))
        for cx, cy, rx, ry, ang in ellipses
    )
    if len(seq) == 1:
        return AutoCollider(
            kind="ellipse", ellipse=seq[0], ellipses=seq, precision=prec, recall=rec,
        )
    return AutoCollider(
        kind="ellipses", ellipse=seq[0], ellipses=seq, precision=prec, recall=rec,
    )


def _choose_auto_collider(
    mask: np.ndarray,
    *,
    force_kind: Optional[str] = None,
) -> AutoCollider:
    """Pick a collider by unified utility: quality minus λ × runtime cost.

    Auto always assumes the sprite may rotate: multi-rect is never a candidate
    (would become multi-OBB/SAT); a 1-rect is offered only if its recall already
    clears ``_AUTO_QUALITY_BAR``. Authors who want a cheap AABB use
    ``hitbox="rect"``.

    ``force_kind`` (lab/debug): ``"circle"``, ``"circles"``, ``"ellipse"``,
    ``"ellipses"``, ``"poly"``, ``"box"`` (single largest rect), ``"boxes"``
    (greedy multi-rect), ``"bbox"`` (silhouette AABB), ``"bbox_ellipse"``
    (ellipse inscribed in that AABB), or ``None`` for the normal policy.
    """
    if mask.size == 0 or not np.any(mask):
        return AutoCollider(kind="none")

    filled = fill_holes(mask)
    lam = float(_AUTO_COST_LAMBDA)
    circle_cap = int(_AUTO_CIRCLE_CAP)
    circle_gate = float(_AUTO_CIRCLE_GATE)
    recall_rail = bool(_AUTO_RECALL_RAIL)
    recall_floor = float(_AUTO_RECALL_FLOOR)

    if force_kind == "bbox":
        box = fit_bbox(filled)
        if box is None:
            return AutoCollider(kind="none")
        x, y, bw, bh = box
        area = max(1, int(bw) * int(bh))
        prec = min(1.0, float(filled.sum()) / float(area))
        return _boxes_collider((box,), prec, 1.0)

    if force_kind == "bbox_ellipse":
        box = fit_bbox(filled)
        if box is None:
            return AutoCollider(kind="none")
        x, y, bw, bh = box
        cx = float(x) + float(bw) * 0.5 - 0.5
        cy = float(y) + float(bh) * 0.5 - 0.5
        rx = max(0.5, float(bw) * 0.5)
        ry = max(0.5, float(bh) * 0.5)
        r_circ = ellipse_as_circle(rx, ry)
        hh, ww = filled.shape
        if r_circ is not None:
            yy = np.arange(hh, dtype=np.float64)[:, None]
            xx = np.arange(ww, dtype=np.float64)[None, :]
            inside = _sq(xx - cx) + _sq(yy - cy) <= r_circ * r_circ
            prec, rec = _shape_metrics(filled, inside, area=math.pi * r_circ * r_circ)
            return AutoCollider(
                kind="circle", circle=(cx, cy, r_circ), circles=((cx, cy, r_circ),),
                precision=prec, recall=rec,
            )
        inside = _ellipse_inside_grid(hh, ww, cx, cy, rx, ry, 0.0)
        prec, rec = _shape_metrics(filled, inside, area=math.pi * rx * ry)
        return AutoCollider(
            kind="ellipse", ellipse=(cx, cy, rx, ry, 0.0),
            ellipses=((cx, cy, rx, ry, 0.0),),
            precision=prec, recall=rec,
        )

    if force_kind == "circle":
        # Lab force: keep a circle even below the auto precision floor so
        # thin/elongated sprites don't bake none → full-sprite rect overlay.
        circ = fit_circle(filled, best_effort=True)
        if circ is not None:
            cx, cy, r, prec, rec = circ
            return AutoCollider(
                kind="circle", circle=(cx, cy, r), circles=((cx, cy, r),),
                precision=prec, recall=rec,
            )
        circs = greedy_circles(filled, max_circles=1)
        if circs:
            prec, rec = _circle_coverage(filled, circs)
            return _circles_collider(circs, prec, rec)
        return AutoCollider(kind="none")

    if force_kind == "circles":
        circs = greedy_circles(filled, max_circles=circle_cap)
        if circs:
            prec, rec = _circle_coverage(filled, circs)
            return _circles_collider(circs, prec, rec)
        return AutoCollider(kind="none")

    if force_kind == "ellipse":
        # Same contract as forced circle: never empty-bake to a full rect.
        ell = fit_ellipse(filled, best_effort=True)
        if ell is not None:
            cx, cy, rx, ry, ang, prec, rec = ell
            r_circ = ellipse_as_circle(rx, ry)
            if r_circ is not None:
                return AutoCollider(
                    kind="circle", circle=(cx, cy, r_circ), circles=((cx, cy, r_circ),),
                    precision=prec, recall=rec,
                )
            return AutoCollider(
                kind="ellipse", ellipse=(cx, cy, rx, ry, ang),
                ellipses=((cx, cy, rx, ry, ang),),
                precision=prec, recall=rec,
            )
        circ = fit_circle(filled, best_effort=True)
        if circ is not None:
            cx, cy, r, prec, rec = circ
            return AutoCollider(
                kind="circle", circle=(cx, cy, r), circles=((cx, cy, r),),
                precision=prec, recall=rec,
            )
        return AutoCollider(kind="none")

    if force_kind == "ellipses":
        # Lab force: skip auto policy floors; fall back so the overlay never
        # shows an empty/none bake (full sprite rect + r=p=0).
        two = fit_two_ellipses(filled, strict=False)
        if two is not None:
            pair, prec, rec = two
            return _ellipses_collider(pair, prec, rec)
        ell = fit_ellipse(filled, best_effort=True)
        if ell is not None:
            cx, cy, rx, ry, ang, prec, rec = ell
            r_circ = ellipse_as_circle(rx, ry)
            if r_circ is not None:
                return AutoCollider(
                    kind="circle", circle=(cx, cy, r_circ), circles=((cx, cy, r_circ),),
                    precision=prec, recall=rec,
                )
            return AutoCollider(
                kind="ellipse", ellipse=(cx, cy, rx, ry, ang),
                ellipses=((cx, cy, rx, ry, ang),),
                precision=prec, recall=rec,
            )
        circ = fit_circle(filled, best_effort=True)
        if circ is not None:
            cx, cy, r, prec, rec = circ
            return AutoCollider(
                kind="circle", circle=(cx, cy, r), circles=((cx, cy, r),),
                precision=prec, recall=rec,
            )
        hull = fit_hull(filled)
        if hull is not None:
            verts, prec, rec = hull
            return AutoCollider(kind="poly", poly=verts, precision=prec, recall=rec)
        rects = greedy_rects(filled)
        if rects:
            one = rects[:1]
            rec, prec = _rect_coverage(filled, one)
            return _boxes_collider(one, prec, rec)
        return AutoCollider(kind="none")

    if force_kind == "poly":
        hull = fit_hull(filled)
        if hull is not None:
            verts, prec, rec = hull
            return AutoCollider(kind="poly", poly=verts, precision=prec, recall=rec)
        return AutoCollider(kind="none")

    if force_kind == "box":
        rects = greedy_rects(filled)
        if rects:
            one = rects[:1]
            rec, prec = _rect_coverage(filled, one)
            return _boxes_collider(one, prec, rec)
        return AutoCollider(kind="none")

    if force_kind == "boxes":
        rects = greedy_rects(filled)
        if rects:
            rec, prec = _rect_coverage(filled, rects)
            return _boxes_collider(rects, prec, rec)
        return AutoCollider(kind="none")

    # (utility, cost, collider) — max utility; ties break to lowest cost.
    candidates: List[Tuple[float, float, AutoCollider]] = []

    def _add(cost: float, quality: float, col: AutoCollider) -> None:
        candidates.append((_utility(quality, cost, lam=lam), float(cost), col))

    circ = fit_circle(filled)
    if circ is not None:
        cx, cy, r, prec, rec = circ
        _add(
            _AUTO_COST_CIRCLE, _quality_score(prec, rec),
            AutoCollider(
                kind="circle", circle=(cx, cy, r), circles=((cx, cy, r),),
                precision=prec, recall=rec,
            ),
        )

    circs = greedy_circles(filled, max_circles=circle_cap)
    for k in range(1, len(circs) + 1):
        prefix = circs[:k]
        prec, rec = _circle_coverage(filled, prefix)
        # Multi-circle with poor recall is a prim explosion without coverage.
        if k >= 2 and rec < circle_gate:
            continue
        _add(k * _AUTO_COST_CIRCLE, _quality_score(prec, rec), _circles_collider(prefix, prec, rec))

    ell = fit_ellipse(filled)
    if ell is not None:
        cx, cy, rx, ry, ang, prec, rec = ell
        r_circ = ellipse_as_circle(rx, ry)
        if r_circ is not None:
            _add(
                _AUTO_COST_CIRCLE, _quality_score(prec, rec),
                AutoCollider(
                    kind="circle", circle=(cx, cy, r_circ), circles=((cx, cy, r_circ),),
                    precision=prec, recall=rec,
                ),
            )
        else:
            _add(
                _AUTO_COST_ELLIPSE, _quality_score(prec, rec),
                AutoCollider(
                    kind="ellipse",
                    ellipse=(cx, cy, rx, ry, ang),
                    ellipses=((cx, cy, rx, ry, ang),),
                    precision=prec,
                    recall=rec,
                ),
            )

    two = fit_two_ellipses(filled)
    if two is not None:
        pair, prec, rec = two
        _add(
            2.0 * _AUTO_COST_ELLIPSE, _quality_score(prec, rec),
            _ellipses_collider(pair, prec, rec),
        )

    hull = fit_hull(filled)
    if hull is not None:
        verts, prec, rec = hull
        _add(
            _hull_runtime_cost(len(verts)), _hull_quality(prec, rec),
            AutoCollider(kind="poly", poly=verts, precision=prec, recall=rec),
        )

    rects = greedy_rects(filled)
    # Never multi-rect (would become multi-OBB under rotation). Single rect
    # only when recall already clears the quality bar.
    if rects:
        rec, prec = _rect_coverage(filled, rects[:1])
        if rec >= _AUTO_QUALITY_BAR:
            _add(
                _rect_runtime_cost(1), _quality_score(prec, rec),
                _boxes_collider(rects[:1], prec, rec),
            )

    if not candidates:
        return AutoCollider(kind="none")

    # Hard recall rail: if any candidate clears the quality bar at high
    # precision, do not pick a severe undershoot.
    pool = candidates
    if recall_rail:
        has_good = any(
            c.recall >= _AUTO_QUALITY_BAR and c.precision >= _AUTO_PRECISION_MIN
            for _, _, c in candidates
        )
        if has_good:
            filtered = [c for c in candidates if c[2].recall >= recall_floor]
            if filtered:
                pool = filtered

    # Unified utility: a slightly worse fit that is much cheaper at runtime
    # beats a polygon that covers every leftover pixel.
    pick = max(pool, key=lambda c: (c[0], -c[1]))
    return pick[2]


def _mask_to_source_circle(
    cx: float, cy: float, r: float, frame: AtlasFrame, sx: float, sy: float,
) -> Tuple[float, float, float, float]:
    """``(cx, cy, rx, ry)`` in source pixels. Axes scale independently."""
    return (
        frame.src_x + (cx + 0.5) * sx,
        frame.src_y + (cy + 0.5) * sy,
        abs(float(r)) * sx,
        abs(float(r)) * sy,
    )


def _mask_to_source_ellipse(
    cx: float, cy: float, rx: float, ry: float, ang: float,
    frame: AtlasFrame, sx: float, sy: float,
) -> Tuple[float, float, float, float, float]:
    return (
        frame.src_x + (cx + 0.5) * sx,
        frame.src_y + (cy + 0.5) * sy,
        rx * sx,
        ry * sy,
        ang,
    )


def _mask_to_source_poly(
    verts: Sequence[Tuple[float, float]], frame: AtlasFrame, sx: float, sy: float,
) -> Tuple[Tuple[float, float], ...]:
    return tuple(
        (frame.src_x + (x + 0.5) * sx, frame.src_y + (y + 0.5) * sy)
        for x, y in verts
    )


def _mask_to_source_boxes(
    boxes: Sequence[Tuple[float, float, float, float]],
    frame: AtlasFrame, sx: float, sy: float,
) -> Tuple[Tuple[float, float, float, float], ...]:
    return tuple(
        (
            frame.src_x + bx * sx,
            frame.src_y + by * sy,
            max(1.0, bw * sx),
            max(1.0, bh * sy),
        )
        for bx, by, bw, bh in boxes
    )


def _auto_key(image, frame: AtlasFrame, force_kind: Optional[str] = None) -> Tuple[Any, ...]:
    """``_AUTO_CACHE`` key: every input of the bake. The trim offset places the
    fit in source space (PA2: aliased frames shared one hitbox), and a rotated
    cell is unrotated first (GR7). ``test_cache_keys`` varies each AtlasFrame
    field against a warm cache."""
    return (
        image_cache_token(image), frame.x, frame.y, frame.w, frame.h,
        bool(frame.rotated), frame.src_x, frame.src_y, frame.src_w, frame.src_h,
        force_kind or "",
    )


def auto_collider_for_frame(
    image: skia.Image,
    frame: AtlasFrame,
    *,
    force_kind: Optional[str] = None,
) -> AutoCollider:
    """Multi-candidate auto hitbox. Cached. Source-space."""
    from .state import as_payload

    force_kind = as_payload(force_kind)
    if frame.boxes and force_kind is None:
        return AutoCollider(kind="boxes", boxes=frame.boxes, precision=1.0, recall=1.0)
    key = _auto_key(image, frame, force_kind)
    hit = _cache_get(_AUTO_CACHE, key)
    if hit is not None:
        return hit
    packed = _display_mask(image, frame)
    mh, mw = packed.shape
    if frame.rotated:
        disp_w, disp_h = float(frame.h), float(frame.w)
    else:
        disp_w, disp_h = float(frame.w), float(frame.h)
    sx = disp_w / float(max(mw, 1))
    sy = disp_h / float(max(mh, 1))
    chosen = _choose_auto_collider(packed, force_kind=force_kind)
    result = _source_collider_from_mask(chosen, frame, sx, sy)
    _cache_put(_AUTO_CACHE, key, result)
    return result


def _display_mask(image: skia.Image, frame: AtlasFrame) -> np.ndarray:
    """Packed alpha mask, un-rotated the same way the blit swaps ``w``/``h``."""
    packed = _mask_for_region(image, frame.x, frame.y, frame.w, frame.h)
    if not frame.rotated:
        return packed
    return np.ascontiguousarray(np.rot90(packed, 1))


def _mask_for_region(image: skia.Image, x: int, y: int, w: int, h: int) -> np.ndarray:
    """Cached downsample of one packed rect. Shared across ``force_kind``."""
    key = (image_cache_token(image), int(x), int(y), int(w), int(h))
    hit = _cache_get(_MASK_CACHE, key)
    if hit is not None:
        return hit
    packed = _downsample_alpha(image, x, y, w, h)
    _cache_put(_MASK_CACHE, key, packed)
    return packed


def _source_collider_from_mask(
    chosen: AutoCollider,
    frame: AtlasFrame,
    sx: float,
    sy: float,
) -> AutoCollider:
    """Map a mask-space collider into ``frame`` source pixels."""
    if not chosen:
        return AutoCollider(kind="none")

    mask_circles: Tuple[Tuple[float, float, float], ...] = ()
    if chosen.circles:
        mask_circles = chosen.circles
    elif chosen.circle is not None:
        mask_circles = (chosen.circle,)

    mask_ellipses: Tuple[Tuple[float, float, float, float, float], ...] = ()
    if chosen.ellipses:
        mask_ellipses = chosen.ellipses
    elif chosen.ellipse is not None:
        mask_ellipses = (chosen.ellipse,)

    if chosen.kind in ("circle", "circles") and mask_circles:
        src_circles = []
        src_ellipses = []
        for cx, cy, r in mask_circles:
            scx, scy, rx, ry = _mask_to_source_circle(cx, cy, r, frame, sx, sy)
            circ = ellipse_as_circle(rx, ry)
            if circ is not None:
                src_circles.append((scx, scy, circ))
            else:
                src_ellipses.append((scx, scy, rx, ry, 0.0))
        if src_ellipses and not src_circles:
            if len(src_ellipses) == 1:
                return AutoCollider(
                    kind="ellipse",
                    ellipse=src_ellipses[0],
                    ellipses=tuple(src_ellipses),
                    precision=chosen.precision,
                    recall=chosen.recall,
                )
            return AutoCollider(
                kind="ellipses",
                ellipse=src_ellipses[0],
                ellipses=tuple(src_ellipses),
                precision=chosen.precision,
                recall=chosen.recall,
            )
        circles_t = tuple(src_circles)
        if len(circles_t) == 1 and not src_ellipses:
            return AutoCollider(
                kind="circle",
                circle=circles_t[0],
                circles=circles_t,
                precision=chosen.precision,
                recall=chosen.recall,
            )
        return AutoCollider(
            kind="circles",
            circles=circles_t,
            ellipses=tuple(src_ellipses),
            precision=chosen.precision,
            recall=chosen.recall,
        )
    if chosen.kind in ("ellipse", "ellipses") and mask_ellipses:
        src_ells = tuple(
            _mask_to_source_ellipse(cx, cy, rx, ry, ang, frame, sx, sy)
            for cx, cy, rx, ry, ang in mask_ellipses
        )
        if len(src_ells) == 1:
            return AutoCollider(
                kind="ellipse",
                ellipse=src_ells[0],
                ellipses=src_ells,
                precision=chosen.precision,
                recall=chosen.recall,
            )
        return AutoCollider(
            kind="ellipses",
            ellipse=src_ells[0],
            ellipses=src_ells,
            precision=chosen.precision,
            recall=chosen.recall,
        )
    if chosen.kind == "poly" and chosen.poly:
        return AutoCollider(
            kind="poly",
            poly=_mask_to_source_poly(chosen.poly, frame, sx, sy),
            precision=chosen.precision,
            recall=chosen.recall,
        )
    if chosen.kind == "boxes" and chosen.boxes:
        return AutoCollider(
            kind="boxes",
            boxes=_mask_to_source_boxes(chosen.boxes, frame, sx, sy),
            precision=chosen.precision,
            recall=chosen.recall,
        )
    return AutoCollider(kind="none")


def _frame_set_signature(
    items: Sequence[Tuple[skia.Image, AtlasFrame]],
) -> Tuple[Any, ...]:
    """Identity of a reference-frame set (sheet + packed rects + pivots)."""
    sig: List[Any] = []
    for image, frame in items:
        sig.append((
            image_cache_token(image),
            int(frame.x), int(frame.y), int(frame.w), int(frame.h),
            int(frame.src_x), int(frame.src_y), int(frame.src_w), int(frame.src_h),
            float(frame.pivot_x), float(frame.pivot_y), bool(frame.rotated),
        ))
    return tuple(sig)


def _union_scales(
    n: int,
    scales: Optional[Sequence[Tuple[float, float]]],
) -> Tuple[Tuple[float, float], ...]:
    """Per-frame (sx, sy): reference-source pixels per this frame's source pixel.

    ``None`` is identity, which is the raw source-pixel overlay.
    """
    if scales is None:
        return ((1.0, 1.0),) * n
    out = tuple((float(sx), float(sy)) for sx, sy in scales)
    if len(out) != n:
        raise ValueError(
            f"union scales: expected {n} pairs, got {len(out)}."
        )
    return out


def union_mask_for_frames(
    items: Sequence[Tuple[skia.Image, AtlasFrame]],
    scales: Optional[Sequence[Tuple[float, float]]] = None,
) -> Tuple[np.ndarray, AtlasFrame, float, float]:
    """Pivot-aligned union of hole-filled masks, in the first item's source space.

    ``scales[i]`` maps frame i's source pixels into that space (identity when
    omitted). The blit scale belongs to the caller: a taller canvas that is
    drawn at the same design height must be scaled down here, or its extra
    pixels hang past the drawn feet.

    Returns ``(mask, synth_frame, sx, sy)``. ``synth_frame`` is a dummy
    ``AtlasFrame`` whose source box is the union AABB; ``sx``/``sy`` map
    mask pixels onto that box so ``_source_collider_from_mask`` lands in
    the first item's source space (pivot-aligned).
    """
    if not items:
        dummy = AtlasFrame("", 0, 0, 1, 1)
        return np.zeros((1, 1), dtype=bool), dummy, 1.0, 1.0

    px_scales = _union_scales(len(items), scales)
    filled_stamps: List[Tuple[np.ndarray, AtlasFrame, float, float, float, float]] = []
    min_rx = min_ry = 1e300
    max_rx = max_ry = -1e300
    for (image, frame), (px_sx, px_sy) in zip(items, px_scales):
        packed = _display_mask(image, frame)
        filled = fill_holes(packed)
        mh, mw = filled.shape
        if frame.rotated:
            disp_w, disp_h = float(frame.h), float(frame.w)
        else:
            disp_w, disp_h = float(frame.w), float(frame.h)
        msx = disp_w / float(max(mw, 1))
        msy = disp_h / float(max(mh, 1))
        filled_stamps.append((filled, frame, msx, msy, px_sx, px_sy))
        piv_x = float(frame.pivot_x) * float(frame.src_w)
        piv_y = float(frame.pivot_y) * float(frame.src_h)
        ys, xs = np.nonzero(filled)
        if xs.size == 0:
            continue
        src_x = float(frame.src_x) + xs.astype(np.float64) * msx
        src_y = float(frame.src_y) + ys.astype(np.float64) * msy
        rel_x = (src_x - piv_x) * px_sx
        rel_y = (src_y - piv_y) * px_sy
        min_rx = min(min_rx, float(rel_x.min()))
        min_ry = min(min_ry, float(rel_y.min()))
        max_rx = max(max_rx, float(rel_x.max()) + msx * px_sx)
        max_ry = max(max_ry, float(rel_y.max()) + msy * px_sy)

    if max_rx <= min_rx or max_ry <= min_ry:
        ref = items[0][1]
        dummy = AtlasFrame(
            "", 0, 0, 1, 1,
            src_x=ref.src_x, src_y=ref.src_y,
            src_w=ref.src_w, src_h=ref.src_h,
            pivot_x=ref.pivot_x, pivot_y=ref.pivot_y,
        )
        return np.zeros((1, 1), dtype=bool), dummy, 1.0, 1.0

    span_x = max(max_rx - min_rx, 1e-6)
    span_y = max(max_ry - min_ry, 1e-6)
    scale = min(1.0, float(_AUTO_MAX_SIDE) / float(max(span_x, span_y)))
    tw = max(1, int(round(span_x * scale)))
    th = max(1, int(round(span_y * scale)))
    union = np.zeros((th, tw), dtype=bool)
    cell_sx = span_x / float(tw)
    cell_sy = span_y / float(th)

    for filled, frame, msx, msy, px_sx, px_sy in filled_stamps:
        piv_x = float(frame.pivot_x) * float(frame.src_w)
        piv_y = float(frame.pivot_y) * float(frame.src_h)
        ys, xs = np.nonzero(filled)
        if xs.size == 0:
            continue
        # Each mask sample covers a source rect ``msx × msy``, not a point.
        # A corner stamp leaves open stripes when the union grid is finer
        # than the per-frame downsample (attack strips), and ``fill_holes``
        # cannot close them. Paint every union cell the rect overlaps.
        # ``px_sx/sy`` are the blit scale into the reference cell, so the
        # footprint shrinks with the sample.
        src_x = float(frame.src_x) + xs.astype(np.float64) * msx
        src_y = float(frame.src_y) + ys.astype(np.float64) * msy
        rel_x0 = (src_x - piv_x) * px_sx - min_rx
        rel_y0 = (src_y - piv_y) * px_sy - min_ry
        foot_x = msx * px_sx
        foot_y = msy * px_sy
        ux0 = np.floor(rel_x0 / cell_sx).astype(np.int64)
        uy0 = np.floor(rel_y0 / cell_sy).astype(np.int64)
        ux1 = np.floor((rel_x0 + foot_x - 1e-6) / cell_sx).astype(np.int64)
        uy1 = np.floor((rel_y0 + foot_y - 1e-6) / cell_sy).astype(np.int64)
        ux0 = np.clip(ux0, 0, tw - 1)
        uy0 = np.clip(uy0, 0, th - 1)
        ux1 = np.clip(np.maximum(ux1, ux0), 0, tw - 1)
        uy1 = np.clip(np.maximum(uy1, uy0), 0, th - 1)
        if np.all(ux0 == ux1) and np.all(uy0 == uy1):
            union[uy0, ux0] = True
        else:
            for x_a, x_b, y_a, y_b in zip(
                ux0.tolist(), ux1.tolist(), uy0.tolist(), uy1.tolist(),
            ):
                union[y_a:y_b + 1, x_a:x_b + 1] = True

    ref = items[0][1]
    ref_piv_x = float(ref.pivot_x) * float(ref.src_w)
    ref_piv_y = float(ref.pivot_y) * float(ref.src_h)
    synth = AtlasFrame(
        "", 0, 0, max(1, int(round(span_x))), max(1, int(round(span_y))),
        src_x=ref_piv_x + min_rx,
        src_y=ref_piv_y + min_ry,
        src_w=ref.src_w,
        src_h=ref.src_h,
        pivot_x=ref.pivot_x,
        pivot_y=ref.pivot_y,
    )
    return union, synth, cell_sx, cell_sy


def auto_collider_for_frames(
    items: Sequence[Tuple[skia.Image, AtlasFrame]],
    *,
    force_kind: Optional[str] = None,
    scales: Optional[Sequence[Tuple[float, float]]] = None,
) -> AutoCollider:
    """Fit one collider to the pivot-aligned union of ``items``. Cached.

    ``scales`` maps each frame into the first item's source pixels before the
    union. Omit it for a raw pixel overlay. A single frame ignores ``scales``
    (that frame is already its own source space).
    """
    from .state import as_payload

    force_kind = as_payload(force_kind)
    items = tuple(items)
    if not items:
        return AutoCollider(kind="none")
    if len(items) == 1:
        return auto_collider_for_frame(items[0][0], items[0][1], force_kind=force_kind)
    # Authored atlas boxes: first frame of the set (documented simplification).
    first_frame = items[0][1]
    if first_frame.boxes and force_kind is None:
        return AutoCollider(
            kind="boxes", boxes=first_frame.boxes, precision=1.0, recall=1.0,
        )
    px_scales = _union_scales(len(items), scales)
    key = (_frame_set_signature(items), force_kind or "", px_scales)
    hit = _cache_get(_UNION_CACHE, key)
    if hit is not None:
        return hit
    packed, synth, sx, sy = union_mask_for_frames(items, px_scales)
    chosen = _choose_auto_collider(packed, force_kind=force_kind)
    result = _source_collider_from_mask(chosen, synth, sx, sy)
    _cache_put(_UNION_CACHE, key, result)    # bounded and purged like the others (PA12)
    return result


def auto_boxes_for_frame(
    image: skia.Image,
    frame: AtlasFrame,
) -> Tuple[Tuple[float, float, float, float], ...]:
    """Rect boxes only (empty when auto picked a circle). Prefer ``auto_collider_for_frame``."""
    return auto_collider_for_frame(image, frame).boxes


def _downsample_alpha(image: skia.Image, x: int, y: int, w: int, h: int) -> np.ndarray:
    """Bool mask, True where alpha >= threshold. Max side ``_AUTO_MAX_SIDE``.

    Nearest-neighbour: linear filtering smears alpha into empty corners and
    makes greedy rects / the circle over-cover transparent pixels.
    """
    w = max(1, int(w))
    h = max(1, int(h))
    scale = min(1.0, float(_AUTO_MAX_SIDE) / float(max(w, h)))
    tw = max(1, int(round(w * scale)))
    th = max(1, int(round(h * scale)))
    info = skia.ImageInfo.Make(tw, th, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    if surf is None:
        return _empty_alpha_mask(th, tw)
    canvas = surf.getCanvas()
    canvas.clear(skia.ColorTRANSPARENT)
    src = skia.Rect.MakeXYWH(float(x), float(y), float(w), float(h))
    dst = skia.Rect.MakeWH(float(tw), float(th))
    canvas.drawImageRect(
        image, src, dst, skia.SamplingOptions(skia.FilterMode.kNearest),
    )
    snap = surf.makeImageSnapshot()
    arr = None if snap is None else snap.toarray(colorType=skia.kRGBA_8888_ColorType)
    if arr is None or arr.size < 4:
        return _empty_alpha_mask(th, tw)
    return arr[:, :, 3] >= _AUTO_ALPHA


def _empty_alpha_mask(th: int, tw: int) -> np.ndarray:
    """No phantom hitbox when the raster surface cannot be read."""
    global _DOWNSAMPLE_WARNED
    if not _DOWNSAMPLE_WARNED:
        _DOWNSAMPLE_WARNED = True
        warnings.warn(
            "Sprite alpha downsample failed; using an empty mask. "
            "The hitbox will not cover this cell.",
            RuntimeWarning,
            stacklevel=3,
        )
    return np.zeros((th, tw), dtype=bool)


def boxes_to_local(
    boxes: Sequence[Tuple[float, float, float, float]],
    frame: AtlasFrame,
) -> Tuple[Tuple[float, float, float, float], ...]:
    """Convert source-space boxes to pivot-relative fractions (cx, cy, w, h), y-up.

    ``cx, cy`` are the box centre as a fraction of ``(src_w, src_h)``, origin at
    the pivot, +x right, +y up. ``w, h`` are fractions of source size.
    """
    sw = float(frame.src_w) or 1.0
    sh = float(frame.src_h) or 1.0
    piv_x = float(frame.pivot_x) * sw
    piv_y = float(frame.pivot_y) * sh
    out: List[Tuple[float, float, float, float]] = []
    for bx, by, bw, bh in boxes:
        bw = max(0.0, float(bw))
        bh = max(0.0, float(bh))
        bcx = float(bx) + bw * 0.5
        bcy = float(by) + bh * 0.5
        cx = (bcx - piv_x) / sw
        cy = (piv_y - bcy) / sh
        out.append((cx, cy, bw / sw, bh / sh))
    return tuple(out)


def circle_to_local(
    cx: float, cy: float, r: float, frame: AtlasFrame,
) -> Tuple[float, float, float]:
    """Pivot-relative (nx, ny, nr). ``nr`` is radius / source width; world r = nr * sprite_w."""
    sw = float(frame.src_w) or 1.0
    sh = float(frame.src_h) or 1.0
    piv_x = float(frame.pivot_x) * sw
    piv_y = float(frame.pivot_y) * sh
    nx = (float(cx) - piv_x) / sw
    ny = (piv_y - float(cy)) / sh
    nr = max(0.0, float(r)) / sw
    return nx, ny, nr


def ellipse_to_local(
    cx: float, cy: float, rx: float, ry: float, ang: float, frame: AtlasFrame,
) -> Tuple[float, float, float, float, float]:
    """Pivot-relative (nx, ny, nrx, nry, ang). Radii are fractions of source size.

    ``ang`` is measured in source-pixel space (x right, y *down*). Mirroring
    y to get the engine's y-*up* local space reverses the sense of rotation,
    so the angle must be negated here — otherwise a tilted ellipse ends up
    mirrored across the horizontal and points away from the shape it's
    meant to cover.
    """
    sw = float(frame.src_w) or 1.0
    sh = float(frame.src_h) or 1.0
    piv_x = float(frame.pivot_x) * sw
    piv_y = float(frame.pivot_y) * sh
    nx = (float(cx) - piv_x) / sw
    ny = (piv_y - float(cy)) / sh
    nrx = max(0.0, float(rx)) / sw
    nry = max(0.0, float(ry)) / sh
    return nx, ny, nrx, nry, -float(ang)


def hull_to_local(
    verts: Sequence[Tuple[float, float]], frame: AtlasFrame,
) -> Tuple[Tuple[float, float], ...]:
    """Pivot-relative verts (nx, ny), y-up."""
    sw = float(frame.src_w) or 1.0
    sh = float(frame.src_h) or 1.0
    piv_x = float(frame.pivot_x) * sw
    piv_y = float(frame.pivot_y) * sh
    out: List[Tuple[float, float]] = []
    for sx, sy in verts:
        nx = (float(sx) - piv_x) / sw
        ny = (piv_y - float(sy)) / sh
        out.append((nx, ny))
    return tuple(out)


def compose_strip(images: Sequence[skia.Image], names: Sequence[str]) -> Tuple[skia.Image, Tuple[AtlasFrame, ...]]:
    """Pack frames left-to-right into one image. Each frame keeps its pixel size."""
    if not images:
        raise ValueError("compose_strip needs at least one image")
    if any(im is None for im in images):
        raise TypeError("compose_strip images must not include None.")
    if len(names) != len(images):
        raise ValueError(
            f"compose_strip expected {len(images)} names, got {len(names)}."
        )
    widths = [max(1, int(im.width())) for im in images]
    heights = [max(1, int(im.height())) for im in images]
    total_w = int(sum(widths))
    max_h = int(max(heights))
    info = skia.ImageInfo.Make(total_w, max_h, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    canvas = surf.getCanvas()
    canvas.clear(skia.ColorTRANSPARENT)
    frames: List[AtlasFrame] = []
    x = 0
    sampling = skia.SamplingOptions(skia.FilterMode.kNearest)
    paint = skia.Paint(AntiAlias=False)
    for im, name, w, h in zip(images, names, widths, heights):
        dst = skia.Rect.MakeXYWH(float(x), 0.0, float(w), float(h))
        canvas.drawImageRect(im, skia.Rect.MakeWH(float(w), float(h)), dst, sampling, paint)
        frames.append(AtlasFrame(str(name), x, 0, w, h))
        x += w
    return surf.makeImageSnapshot(), tuple(frames)


# ---------------------------------------------------------------------------
# FrameFx — lazy silhouette path + SDF (sprite pixel FX)
# ---------------------------------------------------------------------------


class FrameFx:
    """Cached contour + signed-distance field for one image frame region.

    ``path`` is in packed-frame normalized coords (0–1, y-down from the top of
    the packed cell). ``path_v2`` is the same contour simplified for stroke FX.
    ``sdf`` is an A8 image: 128 ≈ edge, >128 outside, <128 inside (lazy —
    path-only looks skip the EDT). ``mask`` is the downsample grid kept so an
    SDF upgrade does not re-raster. ``mw`` / ``mh`` are the bake grid size
    (before SDF pad).
    """

    __slots__ = (
        "path", "path_v2", "sdf", "mask", "mw", "mh", "pad", "empty",
        "n_path", "n_path_v2", "local_v2",
    )

    def __init__(
        self,
        *,
        path: Optional[skia.Path] = None,
        path_v2: Optional[skia.Path] = None,
        sdf: Optional[skia.Image] = None,
        mask: Optional[np.ndarray] = None,
        mw: int = 1,
        mh: int = 1,
        pad: int = 0,
        empty: bool = False,
        n_path: int = 0,
        n_path_v2: int = 0,
    ):
        self.path = path
        self.path_v2 = path_v2
        self.sdf = sdf
        self.mask = mask
        self.mw = max(1, int(mw))
        self.mh = max(1, int(mh))
        self.pad = max(0, int(pad))
        self.empty = bool(empty)
        self.n_path = max(0, int(n_path))
        self.n_path_v2 = max(0, int(n_path_v2))
        self.local_v2: Optional[Dict[tuple, skia.Path]] = None


def frame_fx_for_frame(
    image: skia.Image, frame: AtlasFrame, *, sdf: bool = False,
) -> FrameFx:
    """Lazy bake of silhouette path (+ optional SDF). Interned per frame region.

    Path-only requests skip the EDT. ``sdf=True`` upgrades an existing cache
    entry in place (reuses the retained alpha mask).
    """
    key = (
        image_cache_token(image),
        int(frame.x), int(frame.y), int(frame.w), int(frame.h),
        bool(frame.rotated),                   # the silhouette is unrotated (GR7)
    )
    hit = _cache_get(_FRAME_FX_CACHE, key)
    if hit is None:
        hit = _bake_frame_fx(image, frame, sdf=bool(sdf))
        _cache_put(_FRAME_FX_CACHE, key, hit)
        return hit
    if sdf and not hit.empty and hit.sdf is None:
        _ensure_frame_fx_sdf(hit)
    return hit


def _downsample_alpha_fx(
    image: skia.Image, x: int, y: int, w: int, h: int, *, max_side: int,
) -> np.ndarray:
    """Bool mask for FrameFx (max side ``max_side``). Nearest-neighbour."""
    w = max(1, int(w))
    h = max(1, int(h))
    scale = min(1.0, float(max_side) / float(max(w, h)))
    tw = max(1, int(round(w * scale)))
    th = max(1, int(round(h * scale)))
    info = skia.ImageInfo.Make(tw, th, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    if surf is None:
        return _empty_alpha_mask(th, tw)
    canvas = surf.getCanvas()
    canvas.clear(skia.ColorTRANSPARENT)
    src = skia.Rect.MakeXYWH(float(x), float(y), float(w), float(h))
    dst = skia.Rect.MakeWH(float(tw), float(th))
    canvas.drawImageRect(
        image, src, dst, skia.SamplingOptions(skia.FilterMode.kNearest),
    )
    snap = surf.makeImageSnapshot()
    arr = None if snap is None else snap.toarray(colorType=skia.kRGBA_8888_ColorType)
    if arr is None or arr.size < 4:
        return _empty_alpha_mask(th, tw)
    return arr[:, :, 3] >= _FX_ALPHA


def _bake_frame_fx(
    image: skia.Image, frame: AtlasFrame, *, sdf: bool = False,
) -> FrameFx:
    """Bake contour paths; optionally the SDF. Mask is retained for upgrades."""
    mask = _downsample_alpha_fx(
        image, frame.x, frame.y, frame.w, frame.h, max_side=_FX_MAX_SIDE,
    )
    if frame.rotated:
        mask = np.ascontiguousarray(np.rot90(mask, 1))
    mh, mw = mask.shape
    if not np.any(mask):
        return FrameFx(empty=True, mw=mw, mh=mh, pad=_FX_SDF_PAD, mask=mask)

    padded = np.zeros((mh + 2, mw + 2), dtype=bool)
    padded[1:-1, 1:-1] = mask
    verts = _marching_squares_outer(padded)
    v1 = _cap_contour(verts, max_keep=_FX_PATH_V1_CAP, target=_FX_PATH_V1_TARGET)
    v2 = _simplify_contour_vw(verts, max_verts=_FX_PATH_V2_MAX)
    path = _verts_to_path_norm(v1, mw, mh)
    path_v2 = _verts_to_smooth_path_norm(v2, mw, mh) or _verts_to_path_norm(v2, mw, mh)
    sdf_img = _mask_to_sdf_image(mask, pad=_FX_SDF_PAD) if sdf else None
    return FrameFx(
        path=path, path_v2=path_v2, sdf=sdf_img, mask=mask,
        mw=mw, mh=mh, pad=_FX_SDF_PAD,
        n_path=len(v1), n_path_v2=len(v2),
    )


def _ensure_frame_fx_sdf(fx: FrameFx) -> None:
    """Fill ``fx.sdf`` from the retained mask (no re-raster)."""
    if fx is None or fx.empty or fx.sdf is not None:
        return
    mask = fx.mask
    if mask is None:
        return
    fx.sdf = _mask_to_sdf_image(mask, pad=fx.pad if fx.pad else _FX_SDF_PAD)


def _mask_to_path_norm(mask: np.ndarray) -> Optional[skia.Path]:
    """Outer contour as a path in 0–1 packed-frame coords (y-down). v1 cap."""
    mh, mw = mask.shape
    padded = np.zeros((mh + 2, mw + 2), dtype=bool)
    padded[1:-1, 1:-1] = mask
    verts = _cap_contour(_marching_squares_outer(padded))
    return _verts_to_path_norm(verts, mw, mh)


def _verts_to_path_norm(
    verts: List[Tuple[float, float]], mw: int, mh: int,
) -> Optional[skia.Path]:
    """Packed-cell 0–1 path from padded marching-squares verts."""
    if len(verts) < 3:
        return None
    path = skia.Path()
    x0, y0 = verts[0]
    path.moveTo((x0 - 0.5) / float(mw), (y0 - 0.5) / float(mh))
    for x, y in verts[1:]:
        path.lineTo((x - 0.5) / float(mw), (y - 0.5) / float(mh))
    path.close()
    return path


def _verts_to_smooth_path_norm(
    verts: List[Tuple[float, float]], mw: int, mh: int,
) -> Optional[skia.Path]:
    """Closed quadratic path: edge midpoints on-curve, verts as controls.

    Turns a coarse polygon into rounded borders without a dense polyline.
    """
    if len(verts) < 3:
        return None
    n = len(verts)
    inv_w = 1.0 / float(mw)
    inv_h = 1.0 / float(mh)

    def _n(i: int) -> Tuple[float, float]:
        x, y = verts[i % n]
        return ((x - 0.5) * inv_w, (y - 0.5) * inv_h)

    mids = [None] * n
    for i in range(n):
        x0, y0 = _n(i)
        x1, y1 = _n(i + 1)
        mids[i] = ((x0 + x1) * 0.5, (y0 + y1) * 0.5)
    path = skia.Path()
    path.moveTo(mids[0][0], mids[0][1])
    for i in range(n):
        cx, cy = _n(i + 1)
        ex, ey = mids[(i + 1) % n]
        path.quadTo(cx, cy, ex, ey)
    path.close()
    return path


def _cap_contour(
    verts: List[Tuple[float, float]],
    *,
    max_keep: int = _FX_PATH_V1_CAP,
    target: int = _FX_PATH_V1_TARGET,
) -> List[Tuple[float, float]]:
    """v1 stride cap (unchanged look). Uniform skip — not used for v2."""
    if len(verts) > max_keep:
        step = max(1, len(verts) // max(1, int(target)))
        return verts[::step]
    return verts


def _simplify_contour_vw(
    verts: Sequence[Tuple[float, float]],
    *,
    max_verts: int = _FX_PATH_V2_MAX,
) -> List[Tuple[float, float]]:
    """Visvalingam-Whyatt on a closed ring. Keeps concavities and rounded rims.

    Stops at ``max_verts``. Does not keep eating small stairs — that turns
    rasterized curves into diamonds.
    """
    poly = list(verts)
    if len(poly) >= 2:
        if abs(poly[0][0] - poly[-1][0]) < 1e-6 and abs(poly[0][1] - poly[-1][1]) < 1e-6:
            poly.pop()
    if len(poly) < 3:
        return poly
    cap = max(8, int(max_verts))
    while len(poly) > cap:
        n = len(poly)
        costs = [
            _triangle_area(poly[(i - 1) % n], poly[i], poly[(i + 1) % n])
            for i in range(n)
        ]
        poly.pop(int(np.argmin(costs)))
    return poly


def _marching_squares_outer(mask: np.ndarray) -> List[Tuple[float, float]]:
    """Longest closed contour of a bool mask (True = solid).

    Every island is traced. The topmost start used to win even when a larger
    shape sat below it. The ring used to repeat its first two points (an
    A–B–A spike on close); that tail is dropped.
    """
    mh, mw = mask.shape
    _SEGS = {
        1: [(2, 3)], 2: [(1, 2)], 3: [(1, 3)], 4: [(0, 1)],
        5: [(0, 3), (1, 2)], 6: [(0, 2)], 7: [(0, 3)],
        8: [(0, 3)], 9: [(0, 2)], 10: [(0, 1), (2, 3)], 11: [(0, 1)],
        12: [(1, 3)], 13: [(1, 2)], 14: [(2, 3)],
    }

    def _case(r: int, c: int) -> int:
        tl = 1 if mask[r, c] else 0
        tr = 1 if mask[r, c + 1] else 0
        br = 1 if mask[r + 1, c + 1] else 0
        bl = 1 if mask[r + 1, c] else 0
        return (tl << 3) | (tr << 2) | (br << 1) | bl

    def _pt(r: int, c: int, edge: int) -> Tuple[float, float]:
        if edge == 0:
            return (c + 0.5, float(r))
        if edge == 1:
            return (float(c + 1), r + 0.5)
        if edge == 2:
            return (c + 0.5, float(r + 1))
        return (float(c), r + 0.5)

    def _near(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
        return abs(a[0] - b[0]) <= 1e-6 and abs(a[1] - b[1]) <= 1e-6

    def _length(pts: Sequence[Tuple[float, float]]) -> float:
        total = 0.0
        for i in range(len(pts)):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % len(pts)]
            total += math.hypot(x1 - x0, y1 - y0)
        return total

    visited: set = set()

    def _trace(sr: int, sc: int, case: int) -> List[Tuple[float, float]]:
        segs = _SEGS.get(case, [])
        if not segs:
            return []
        e_from, e_to = segs[0]
        if (sr, sc, e_to) in visited:
            return []
        points: List[Tuple[float, float]] = [_pt(sr, sc, e_from)]
        r, c, cur_edge = sr, sc, e_to
        for _ in range(mw * mh * 4):
            points.append(_pt(r, c, cur_edge))
            key = (r, c, cur_edge)
            if key in visited and len(points) > 4:
                break
            visited.add(key)
            if cur_edge == 0:
                nr, nc, enter = r - 1, c, 2
            elif cur_edge == 1:
                nr, nc, enter = r, c + 1, 3
            elif cur_edge == 2:
                nr, nc, enter = r + 1, c, 0
            else:
                nr, nc, enter = r, c - 1, 1
            if nr < 0 or nc < 0 or nr >= mh - 1 or nc >= mw - 1:
                break
            nsegs = _SEGS.get(_case(nr, nc), [])
            nxt = None
            for a, b in nsegs:
                if a == enter:
                    nxt = b
                    break
                if b == enter:
                    nxt = a
                    break
            if nxt is None:
                break
            r, c, cur_edge = nr, nc, nxt
            if (r, c) == (sr, sc) and cur_edge == e_from and len(points) > 4:
                break
        out: List[Tuple[float, float]] = []
        for p in points:
            if not out or not _near(out[-1], p):
                out.append(p)
        if len(out) >= 2 and _near(out[0], out[-1]):
            out.pop()
        if (
            len(out) >= 4
            and _near(out[-2], out[0])
            and _near(out[-1], out[1])
        ):
            out = out[:-2]
        return out

    best: List[Tuple[float, float]] = []
    best_len = -1.0
    for r in range(mh - 1):
        for c in range(mw - 1):
            case = _case(r, c)
            if not (0 < case < 15):
                continue
            contour = _trace(r, c, case)
            if len(contour) < 3:
                continue
            length = _length(contour)
            if length > best_len:
                best = contour
                best_len = length
    return best


def _edt_1d(f: np.ndarray) -> np.ndarray:
    """Felzenszwalb 1D squared Euclidean distance transform."""
    n = int(f.shape[0])
    d = np.empty(n, dtype=np.float64)
    v = np.empty(n, dtype=np.int32)
    z = np.empty(n + 1, dtype=np.float64)
    k = 0
    v[0] = 0
    z[0] = -1e20
    z[1] = 1e20
    for q in range(1, n):
        s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2.0 * q - 2.0 * v[k])
        while s <= z[k]:
            k -= 1
            s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2.0 * q - 2.0 * v[k])
        k += 1
        v[k] = q
        z[k] = s
        z[k + 1] = 1e20
    k = 0
    for q in range(n):
        while z[k + 1] < q:
            k += 1
        d[q] = (q - v[k]) * (q - v[k]) + f[v[k]]
    return d


def _edt_2d(binary: np.ndarray) -> np.ndarray:
    """Squared distance to nearest False (for True cells) / True (for False).

    Input True = solid. Returns signed distance: negative inside, positive outside
    (in pixel units, not squared).
    """
    h, w = binary.shape
    INF = 1e10
    # Distance to nearest solid for every cell (0 on solid).
    f = np.where(binary, 0.0, INF)
    # Columns
    for x in range(w):
        f[:, x] = _edt_1d(f[:, x])
    # Rows
    for y in range(h):
        f[y, :] = _edt_1d(f[y, :])
    dist_out = np.sqrt(f)  # distance to solid (= 0 inside, >0 outside)

    # Distance to nearest empty for solid cells
    g = np.where(~binary, 0.0, INF)
    for x in range(w):
        g[:, x] = _edt_1d(g[:, x])
    for y in range(h):
        g[y, :] = _edt_1d(g[y, :])
    dist_in = np.sqrt(g)

    signed = dist_out.copy()
    signed[binary] = -dist_in[binary]
    return signed


def _mask_to_sdf_image(mask: np.ndarray, *, pad: int = 8) -> Optional[skia.Image]:
    """A8 SDF: 128 = edge, >128 outside, <128 inside. Padded for outer glow."""
    mh, mw = mask.shape
    p = max(0, int(pad))
    if p:
        big = np.zeros((mh + 2 * p, mw + 2 * p), dtype=bool)
        big[p:p + mh, p:p + mw] = mask
    else:
        big = mask
    signed = _edt_2d(big)
    scale = 128.0 / max(float(max(mh, mw)) * 0.5, 8.0)
    encoded = np.clip(128.0 + signed * scale, 0.0, 255.0).astype(np.uint8)
    bh, bw = encoded.shape
    # Pack into RGBA (R=G=B=sdf, A=255) for portable MakeRaster upload.
    rgba = np.empty((bh, bw, 4), dtype=np.uint8)
    rgba[:, :, 0] = encoded
    rgba[:, :, 1] = encoded
    rgba[:, :, 2] = encoded
    rgba[:, :, 3] = 255
    info = skia.ImageInfo.Make(bw, bh, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    if surf is None:
        return None
    # Write pixels via pixmap
    img = skia.Image.MakeRasterCopy(
        skia.Pixmap(info, bytearray(np.ascontiguousarray(rgba).tobytes()), bw * 4),
    )
    if img is None:
        # Fallback: draw as bitmap via canvas
        canvas = surf.getCanvas()
        canvas.clear(skia.ColorBLACK)
        return surf.makeImageSnapshot()
    return img

