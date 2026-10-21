"""Level file format (``*.json`` made by the level editor): parse, check, write.

Pure data — no Graphics. ``scena.level.Level`` reads files through
:func:`parse`; the level editor (``scena_editor``) writes them through
:func:`serialize`. :func:`constructor_for` is the one kind → constructor
table: ``LevelItem.make()`` and the editor's "Copy as code" both use it, so
the shape made in code and the line copied from the editor never disagree.

A level file::

    {"format": "scena-level", "version": 2, "size": [3600, 1500],
     "sheets": [{"name": "terreno", "file": "tiles.png", "cell": [16, 16]}],
     "items": [{"kind": "rect", "groups": ["plataforma"], "center": [450, 170],
                "width": 220, "height": 24, "angle": 20},
               {"kind": "image", "sheet": "terreno", "frame": 37, "center": [8, 8],
                "width": 16, "height": 16}, ...]}

``sheets`` (optional) lists the spritesheets that image items cut frames from:
one image cut one way, the layouts of ``Sheet`` (``cols`` / ``rows``,
``cell``, ``atlas``). An image item holds either a whole ``file`` or a
``sheet`` + ``frame``.

Design units, y up, ``angle`` in degrees counter-clockwise — the same
numbers an author writes in code. ``items`` order is the draw order. See
``design/Editor Design.md``.
"""
from __future__ import annotations

import keyword
import math
from typing import Any, Dict, List, Optional, Tuple

from .validate import did_you_mean

FORMAT = "scena-level"
# 2 (0.9.0): the ``sheets`` table and frame images. Every version up to this
# one is read; the editor always writes this one.
VERSION = 2
# Older spellings of the tag, still read (written as ``FORMAT``). The framework
# was renamed Stage → Scena in 0.6.0; only the tag changed, so the version did
# not move: a "stage-level" version-1 file is the same data.
LEGACY_FORMATS = ("stage-level",)

# Per kind: required geometry fields, optional fields with their defaults.
# Every kind also takes the common fields below.
_POINT = "point"      # an (x, y) pair
_POINTS = "points"    # a list of (x, y) pairs
_SIZE = "size"        # a number >= 0
_NUMBER = "number"    # any finite number
_BOOL = "bool"
_TEXT = "text"        # a non-empty string
_FRACTION = "fraction"  # a number from 0 to 1
_SIDES = "sides"      # a whole number >= 3
_RATIO = "ratio"      # a number above 0 and below 2 (Triangle base_ratio=)
_SCOOP = "scoop"      # a named point of the box (Concave scoop=)
_RIM = "rim"          # a pair [x, y] of numbers >= 0 (Concave rim=)
_NAME = "name"        # a Python identifier (a sheet's name: also a variable in code)
_FRAME = "frame"      # a whole number >= 0 or a non-empty string (Sprite frame=)
_COUNT = "count"      # a whole number >= 1 (Sheet cols= / rows=)
_CELL = "cell"        # a pair [w, h] of whole numbers >= 1 (Sheet cell=)

# Where a concave item's scoop may sit (Concave's ``scoop=``).
SCOOPS = ("top_left", "top_right", "bottom_left", "bottom_right",
          "top_center", "bottom_center", "left_center", "right_center")

KINDS: Dict[str, Dict[str, Any]] = {
    "rect": {"required": {"center": _POINT, "width": _SIZE, "height": _SIZE},
             "optional": {"angle": (_NUMBER, 0.0)}},
    "ellipse": {"required": {"center": _POINT, "width": _SIZE, "height": _SIZE},
                "optional": {"angle": (_NUMBER, 0.0)}},
    "concave": {"required": {"center": _POINT, "width": _SIZE, "height": _SIZE},
                "optional": {"angle": (_NUMBER, 0.0), "scoop": (_SCOOP, "top_left"),
                             "rim": (_RIM, (0.0, 0.0))}},
    "circle": {"required": {"center": _POINT, "radius": _SIZE}, "optional": {}},
    "line": {"required": {"p1": _POINT, "p2": _POINT}, "optional": {}},
    "polygon": {"required": {"points": _POINTS}, "optional": {}},
    "regular_polygon": {"required": {"center": _POINT, "radius": _SIZE, "n": _SIDES},
                        "optional": {"angle": (_NUMBER, 0.0)}},
    "triangle": {"required": {"center": _POINT, "radius": _SIZE},
                 "optional": {"angle": (_NUMBER, 0.0), "base_ratio": (_RATIO, 1.0)}},
    "track": {"required": {"points": _POINTS},
              "optional": {"closed": (_BOOL, False), "smooth": (_FRACTION, 0.0)}},
    "point": {"required": {"center": _POINT}, "optional": {}},
    # Either ``file`` (a whole picture) or ``sheet`` + ``frame`` (one frame of
    # a sheet in the ``sheets`` table): checked in ``parse_item``.
    "image": {"required": {"center": _POINT, "width": _SIZE, "height": _SIZE},
              "optional": {"file": (_TEXT, None), "sheet": (_NAME, None),
                           "frame": (_FRAME, None),
                           "angle": (_NUMBER, 0.0), "guide": (_BOOL, False)}},
}
# Fewest points a kind can hold (a polygon needs an area, a track a direction).
MIN_POINTS = {"polygon": 3, "track": 2}
# Common to every kind. ``locked`` is editor-only (the game ignores it).
COMMON_OPTIONAL = {"name": None, "groups": (), "locked": False}
# Kinds whose item is a region (``LevelItem.box``).
AREA_KINDS = frozenset({"rect", "ellipse", "concave", "circle", "image"})
# Keys and kinds from before a rename: refused with the new spelling (no
# silent rewrite, no alias).
_RENAMED = {"rotation": "angle"}
_RENAMED_KINDS = {"path": "track"}
# Key order when writing (readable diffs).
_KEY_ORDER = ("kind", "name", "groups", "file", "sheet", "frame", "center", "p1", "p2", "points",
              "width", "height", "radius", "n", "angle", "base_ratio", "scoop", "rim", "closed",
              "smooth", "guide", "locked")


# A sheet entry: its name, its image, and exactly one layout (``Sheet``'s).
SHEET_KEYS = ("name", "file", "cols", "rows", "cell", "atlas")
SHEET_LAYOUTS = ("cols", "cell", "atlas")
# Sheet keywords that are not geometry: time and registration stay in code.
_NOT_IN_SHEET = {
    "fps": "clips", "yoyo": "clips", "clips": "clips", "clip": "clips",
    "anchor": "anchor", "pixel_size": "pixel_size",
}
_TOP_KEYS = ("format", "version", "size", "sheets", "items")


class LevelFormatError(ValueError):
    """A level file that Scena cannot read: wrong format, bad item, newer version."""


def _where(source: str, index: Optional[int] = None, item: Any = None) -> str:
    out = source if isinstance(source, str) and source else "level"
    if index is not None:
        out += f": item {index}"
        if isinstance(item, dict):
            kind = item.get("kind")
            name = item.get("name")
            if isinstance(kind, str):
                out += f" ({kind}" + (f" {name!r}" if isinstance(name, str) else "") + ")"
    return out


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LevelFormatError(f"{what} must be a number, got {value!r}")
    n = float(value)
    if not math.isfinite(n):
        raise LevelFormatError(f"{what} must be a finite number, got {value!r}")
    return n


def _point(value: Any, what: str) -> Tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise LevelFormatError(f"{what} must be a pair [x, y], got {value!r}")
    return (_number(value[0], what), _number(value[1], what))


def _field(kind_of: str, value: Any, what: str) -> Any:
    if kind_of == _POINT:
        return _point(value, what)
    if kind_of == _POINTS:
        if not isinstance(value, (list, tuple)):
            raise LevelFormatError(f"{what} must be a list of [x, y] pairs, got {value!r}")
        return tuple(_point(p, f"{what}[{i}]") for i, p in enumerate(value))
    if kind_of == _SIZE:
        n = _number(value, what)
        if n < 0:
            raise LevelFormatError(f"{what} must be >= 0, got {value!r}")
        return n
    if kind_of == _NUMBER:
        return _number(value, what)
    if kind_of == _SIDES:
        n = _number(value, what)
        if n != int(n) or n < 3:
            raise LevelFormatError(f"{what} must be a whole number >= 3, got {value!r}")
        return int(n)
    if kind_of == _RATIO:
        n = _number(value, what)
        if not 0.0 < n < 2.0:
            raise LevelFormatError(f"{what} must be above 0 and below 2, got {value!r}")
        return n
    if kind_of == _FRACTION:
        n = _number(value, what)
        if not 0.0 <= n <= 1.0:
            raise LevelFormatError(f"{what} must be from 0 to 1, got {value!r}")
        return n
    if kind_of == _BOOL:
        if not isinstance(value, bool):
            raise LevelFormatError(f"{what} must be true or false, got {value!r}")
        return value
    if kind_of == _TEXT:
        if not isinstance(value, str) or not value.strip():
            raise LevelFormatError(f"{what} must be a non-empty string, got {value!r}")
        return value
    if kind_of == _SCOOP:
        if value not in SCOOPS:
            raise LevelFormatError(
                f"{what} must be one of {', '.join(SCOOPS)}, got {value!r}."
                + did_you_mean(value, SCOOPS)
            )
        return value
    if kind_of == _RIM:
        x, y = _point(value, what)
        if x < 0 or y < 0:
            raise LevelFormatError(f"{what} must be >= 0 on both axes, got {value!r}")
        return (x, y)
    if kind_of == _NAME:
        if not isinstance(value, str) or not value.isidentifier() or keyword.iskeyword(value):
            raise LevelFormatError(
                f"{what} must be a name made of letters, digits and _ (not starting "
                f"with a digit), got {value!r}: it is also a variable name in code"
            )
        return value
    if kind_of == _FRAME:
        if isinstance(value, str):
            if not value.strip():
                raise LevelFormatError(f"{what} must be a frame index or name, got {value!r}")
            return value
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        n = _number(value, what) if ok else None
        if n is None or n != int(n) or n < 0:
            raise LevelFormatError(
                f"{what} must be a whole number >= 0 (an index) or a frame name, got {value!r}"
            )
        return int(n)
    if kind_of == _COUNT:
        n = _number(value, what)
        if n != int(n) or n < 1:
            raise LevelFormatError(f"{what} must be a whole number >= 1, got {value!r}")
        return int(n)
    if kind_of == _CELL:
        w, h = _point(value, what)
        if w != int(w) or h != int(h) or w < 1 or h < 1:
            raise LevelFormatError(
                f"{what} must be a pair [w, h] of whole pixels >= 1, got {value!r}"
            )
        return (int(w), int(h))
    raise AssertionError(kind_of)


def _groups(value: Any, what: str) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise LevelFormatError(f"{what} must be a list of names, got {value!r}")
    out: List[str] = []
    for g in value:
        if not isinstance(g, str) or not g.strip():
            raise LevelFormatError(f"{what} must hold non-empty names, got {g!r}")
        if g in out:
            raise LevelFormatError(f"{what} lists {g!r} twice")
        out.append(g)
    return tuple(out)


def parse_item(raw: Any, *, where: str = "item") -> Dict[str, Any]:
    """One item dict → normalized dict (every field present, tuples for points)."""
    if not isinstance(raw, dict):
        raise LevelFormatError(f"{where} must be an object with a 'kind', got {raw!r}")
    kind = raw.get("kind")
    if kind in _RENAMED_KINDS:
        raise LevelFormatError(
            f"{where}: the kind {kind!r} is now {_RENAMED_KINDS[kind]!r} (the Scena class "
            f"it makes). Rename the kind in the file."
        )
    if kind not in KINDS:
        raise LevelFormatError(
            f"{where}: unknown kind {kind!r}. Kinds: {', '.join(KINDS)}."
            + did_you_mean(kind, KINDS)
        )
    spec = KINDS[kind]
    allowed = {"kind"} | set(spec["required"]) | set(spec["optional"]) | set(COMMON_OPTIONAL)
    for key in raw:
        if key in _RENAMED and _RENAMED[key] in allowed:
            raise LevelFormatError(
                f"{where}: {key!r} is now {_RENAMED[key]!r} (degrees, counter-clockwise, "
                f"the same word as Graphic.angle and Box.angle). Rename the key in the file."
            )
        if key not in allowed:
            raise LevelFormatError(
                f"{where}: a {kind} has no {key!r}. It takes: "
                f"{', '.join(k for k in _KEY_ORDER if k in allowed)}."
                + did_you_mean(key, allowed)
            )
    item: Dict[str, Any] = {"kind": kind}
    for key, kind_of in spec["required"].items():
        if key not in raw:
            raise LevelFormatError(f"{where}: a {kind} needs {key!r}")
        item[key] = _field(kind_of, raw[key], f"{where}: {key}")
    for key, (kind_of, default) in spec["optional"].items():
        item[key] = _field(kind_of, raw[key], f"{where}: {key}") if key in raw else default
    if kind in MIN_POINTS and len(item["points"]) < MIN_POINTS[kind]:
        raise LevelFormatError(
            f"{where}: a {kind} needs at least {MIN_POINTS[kind]} points, "
            f"got {len(item['points'])}"
        )
    if kind == "image":
        _check_image_source(item, where)
    name = raw.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise LevelFormatError(f"{where}: name must be a non-empty string, got {name!r}")
    item["name"] = name
    item["groups"] = _groups(raw.get("groups", ()), f"{where}: groups")
    item["locked"] = _field(_BOOL, raw.get("locked", False), f"{where}: locked")
    return item


def _check_image_source(item: Dict[str, Any], where: str) -> None:
    """An image is a whole ``file`` or ``sheet`` + ``frame``: exactly one."""
    file, sheet, frame = item["file"], item["sheet"], item["frame"]
    if file is not None and (sheet is not None or frame is not None):
        raise LevelFormatError(
            f"{where}: an image takes 'file' (a whole picture) or 'sheet' + 'frame' "
            "(one frame of a sheet), not both. Remove one."
        )
    if file is None and sheet is None:
        raise LevelFormatError(
            f"{where}: an image needs 'file' (a whole picture) or 'sheet' + 'frame' "
            "(one frame of a sheet)"
        )
    if sheet is not None and frame is None:
        raise LevelFormatError(
            f"{where}: 'sheet' needs 'frame' (the index or name of the frame to show)"
        )
    if frame is not None and sheet is None:
        raise LevelFormatError(f"{where}: 'frame' needs 'sheet' (the sheet it is cut from)")


def parse_sheet(raw: Any, *, where: str = "sheet") -> Dict[str, Any]:
    """One ``sheets`` entry → normalized dict (every key of ``SHEET_KEYS``).

    The layout rules and words of ``Sheet``: exactly one of ``cols`` (with
    optional ``rows``), ``cell`` or ``atlas``.
    """
    if not isinstance(raw, dict):
        raise LevelFormatError(f"{where} must be an object with a 'name' and a 'file', got {raw!r}")
    for key in raw:
        if key in _NOT_IN_SHEET:
            what = _NOT_IN_SHEET[key]
            hint = {
                "clips": "Clips are time, so they live in code: "
                         'level.sheet("name").clip("walk", [0, 1, 2], fps=8).',
                "anchor": "A level item's center is the box's center; the level's sheets "
                          "use the default anchor.",
                "pixel_size": "Every image item carries its own width and height.",
            }[what]
            raise LevelFormatError(f"{where}: a level sheet has no {key!r}. {hint}")
        if key not in SHEET_KEYS:
            raise LevelFormatError(
                f"{where}: a sheet has no {key!r}. It takes: {', '.join(SHEET_KEYS)}."
                + did_you_mean(key, SHEET_KEYS)
            )
    for key in ("name", "file"):
        if key not in raw:
            raise LevelFormatError(f"{where}: a sheet needs {key!r}")
    entry: Dict[str, Any] = {
        "name": _field(_NAME, raw["name"], f"{where}: name"),
        "file": _field(_TEXT, raw["file"], f"{where}: file"),
        "cols": _field(_COUNT, raw["cols"], f"{where}: cols") if "cols" in raw else None,
        "rows": _field(_COUNT, raw["rows"], f"{where}: rows") if "rows" in raw else None,
        "cell": _field(_CELL, raw["cell"], f"{where}: cell") if "cell" in raw else None,
        "atlas": _field(_TEXT, raw["atlas"], f"{where}: atlas") if "atlas" in raw else None,
    }
    if entry["rows"] is not None and entry["cols"] is None:
        raise LevelFormatError(
            f"{where}: rows needs cols (cols 1 for a vertical strip), as Sheet's rows= needs cols="
        )
    layouts = [k for k in SHEET_LAYOUTS if entry[k] is not None]
    if not layouts:
        raise LevelFormatError(
            f"{where}: a sheet needs a layout: cols (and rows), cell or atlas — "
            "as Sheet(cols=…, rows=…), Sheet(cell=(w, h)) or Sheet(atlas=…). "
            "A whole picture is an image item with 'file'."
        )
    if len(layouts) > 1:
        raise LevelFormatError(
            f"{where}: {' and '.join(layouts)} cannot be combined. cols / rows cut the "
            "image by count, cell by pixel size, atlas by the coordinates in a JSON / XML "
            "file: one of them, as Sheet."
        )
    return entry


_OWN_DATA_HINT = ("For a map in your own format, read it yourself: "
                  "import json; dados = json.load(open(path)).")


def parse(data: Any, *, source: str = "level") -> Dict[str, Any]:
    """A decoded level file → ``{"size": (w, h), "sheets": [..], "items": [..]}``
    (normalized).

    Raises :class:`LevelFormatError` (a ``ValueError``) naming ``source`` and
    the item, never half-reads a file.
    """
    if not isinstance(data, dict) or (
        data.get("format") != FORMAT and data.get("format") not in LEGACY_FORMATS
    ):
        raise LevelFormatError(
            f"{source} is not a Scena level file (no \"format\": \"{FORMAT}\"). "
            "Level files are made by the level editor: python -m scena_editor. "
            + _OWN_DATA_HINT
        )
    version = data.get("version")
    if version is None:
        # The format tag added by hand to one's own map (persona probes R3-10:
        # the next message led field by field toward forging an editor file).
        raise LevelFormatError(
            f"{source} has the level format tag but no version: it does not look "
            f"like a file the level editor wrote. " + _OWN_DATA_HINT
        )
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise LevelFormatError(f"{source}: version must be a whole number >= 1, got {version!r}")
    if version > VERSION:
        raise LevelFormatError(
            f"{source} was saved by a newer Scena (level version {version}; this "
            f"Scena reads up to {VERSION}). Update Scena."
        )
    for key in data:
        if key not in _TOP_KEYS:
            raise LevelFormatError(
                f"{source}: unknown top-level key {key!r}. Keys: {', '.join(_TOP_KEYS)}."
                + did_you_mean(key, _TOP_KEYS)
            )
    size = _point(data.get("size"), f"{source}: size")
    if size[0] < 0 or size[1] < 0:
        raise LevelFormatError(f"{source}: size must be >= 0, got {list(size)}")
    raw_sheets = data.get("sheets", [])
    if not isinstance(raw_sheets, list):
        raise LevelFormatError(f"{source}: sheets must be a list, got {raw_sheets!r}")
    sheets = []
    sheet_names: Dict[str, int] = {}
    for i, raw in enumerate(raw_sheets):
        label = f"{source}: sheet {i}" + (
            f" ({raw['name']!r})" if isinstance(raw, dict) and isinstance(raw.get("name"), str)
            else "")
        entry = parse_sheet(raw, where=label)
        if entry["name"] in sheet_names:
            raise LevelFormatError(
                f"{label}: the name {entry['name']!r} is already used by sheet "
                f"{sheet_names[entry['name']]}. Sheet names are unique in a level."
            )
        sheet_names[entry["name"]] = i
        sheets.append(entry)
    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        raise LevelFormatError(f"{source}: items must be a list, got {raw_items!r}")
    items = []
    names: Dict[str, int] = {}
    for i, raw in enumerate(raw_items):
        item = parse_item(raw, where=_where(source, i, raw))
        name = item["name"]
        if name is not None:
            if name in names:
                raise LevelFormatError(
                    f"{_where(source, i, raw)}: the name {name!r} is already used by "
                    f"item {names[name]}. Names are unique in a level."
                )
            names[name] = i
        sheet = item.get("sheet")
        if sheet is not None and sheet not in sheet_names:
            raise LevelFormatError(
                f"{_where(source, i, raw)}: no sheet named {sheet!r} in the level's sheets."
                + (did_you_mean(sheet, sheet_names) or (
                    f" Sheets: {', '.join(sheet_names)}." if sheet_names
                    else " The level has no sheets."))
            )
        items.append(item)
    return {"size": size, "sheets": sheets, "items": items}


def serialize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalized item → JSON-ready dict; fields at their default are left out."""
    kind = item["kind"]
    spec = KINDS[kind]
    out: Dict[str, Any] = {}
    for key in _KEY_ORDER:
        if key == "kind":
            out[key] = kind
        elif key in spec["required"]:
            out[key] = _plain(item[key])
        elif key in spec["optional"]:
            if item.get(key, spec["optional"][key][1]) != spec["optional"][key][1]:
                out[key] = _plain(item[key])
        elif key in COMMON_OPTIONAL:
            value = item.get(key, COMMON_OPTIONAL[key])
            if value not in (None, False, (), []):
                out[key] = _plain(value)
    return out


def serialize_sheet(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Normalized sheet entry → JSON-ready dict (unset layout keys left out)."""
    return {k: _plain(entry[k]) for k in SHEET_KEYS if entry.get(k) is not None}


def serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """``{"size": .., "sheets": [..], "items": [..]}`` (normalized) → a JSON-ready
    level file dict. ``sheets`` is left out when empty; the version is always
    :data:`VERSION`."""
    out: Dict[str, Any] = {"format": FORMAT, "version": VERSION, "size": _plain(doc["size"])}
    sheets = doc.get("sheets") or ()
    if sheets:
        out["sheets"] = [serialize_sheet(e) for e in sheets]
    out["items"] = [serialize_item(item) for item in doc["items"]]
    return out


def dumps(data: Dict[str, Any]) -> str:
    """A level file dict (from :func:`serialize`) as text: one item per line,
    so the file reads like a list and diffs line by line."""
    import json
    head = {k: data[k] for k in ("format", "version", "size")}
    out = [json.dumps(head, ensure_ascii=False)[:-1]]
    sheets = data.get("sheets") or []
    if sheets:
        out[0] += ', "sheets": ['
        for entry in sheets:
            out.append("  " + json.dumps(entry, ensure_ascii=False) + ",")
        out[-1] = out[-1][:-1]
        out.append('], "items": [')
    else:
        out[0] += ', "items": ['
    items = data.get("items", [])
    for i, item in enumerate(items):
        out.append("  " + json.dumps(item, ensure_ascii=False) + ("," if i < len(items) - 1 else ""))
    out.append("]}")
    return "\n".join(out) + "\n"


def _plain(value: Any) -> Any:
    """Tuples → lists; float noise rounded off (``239.99999999999994`` → ``240``);
    integral floats → ints. A hand-readable file."""
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float):
        value = round(value, 6) + 0.0
        if value.is_integer() and abs(value) < 1e15:
            return int(value)
    return value


# ---------------------------------------------------------------------------
# The kind → constructor table (LevelItem.make and the editor's Copy as code)
# ---------------------------------------------------------------------------

class SheetVar:
    """A sheet's variable in Copy as code: prints as its bare name."""

    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return self.name


def constructor_for(item: Dict[str, Any], *, image: Optional[str] = None,
                    sheet: Any = None
                    ) -> Tuple[str, tuple, Dict[str, Any], Dict[str, Any]]:
    """``(class name, positional args, keyword args, settings after construction)``.

    ``image`` is the image path to pass (absolute in ``make()``, as written in
    the file for Copy as code). ``sheet`` is a frame image's ``Sheet`` in
    ``make()``; left out, a :class:`SheetVar` named as the file names the sheet
    (Copy as code). Groups are not included — the caller adds ``group=``.
    ``settings`` holds attributes to assign after construction (none today:
    every kind's fields are constructor keywords).
    """
    kind = item["kind"]
    if kind in ("rect", "ellipse"):
        kwargs = {"center": item["center"], "width": item["width"], "height": item["height"]}
        if item["angle"]:
            kwargs["angle"] = item["angle"]
        return ("Rect" if kind == "rect" else "Ellipse"), (), kwargs, {}
    if kind == "concave":
        kwargs = {"center": item["center"], "width": item["width"], "height": item["height"]}
        if item["angle"]:
            kwargs["angle"] = item["angle"]
        if item["scoop"] != "top_left":
            kwargs["scoop"] = item["scoop"]
        mx, my = item["rim"]
        if mx or my:
            kwargs["rim"] = mx if mx == my else (mx, my)
        return "Concave", (), kwargs, {}
    if kind == "circle":
        return "Circle", (), {"center": item["center"], "radius": item["radius"]}, {}
    if kind == "line":
        return "Line", (), {"p1": item["p1"], "p2": item["p2"]}, {}
    if kind == "polygon":
        return "Polygon", (), {"points": list(item["points"])}, {}
    if kind == "regular_polygon":
        kwargs = {"n": item["n"], "center": item["center"], "radius": item["radius"]}
        if item["angle"]:
            kwargs["angle"] = item["angle"]
        return "RegularPolygon", (), kwargs, {}
    if kind == "triangle":
        kwargs = {"center": item["center"], "radius": item["radius"]}
        if item["angle"]:
            kwargs["angle"] = item["angle"]
        if item["base_ratio"] != 1.0:
            kwargs["base_ratio"] = item["base_ratio"]
        return "Triangle", (), kwargs, {}
    if kind == "track":
        # smooth always written: Track's own default is 1 (a curve), the
        # file's is 0 (straight segments, as the editor draws by default).
        kwargs = {"points": list(item["points"]), "smooth": item["smooth"]}
        if item["closed"]:
            kwargs["closed"] = True
        return "Track", (), kwargs, {}
    if kind == "point":
        return "Point", tuple(item["center"]), {}, {}
    if kind == "image":
        kwargs = {}
        if item.get("sheet") is not None:
            source = SheetVar(item["sheet"]) if sheet is None else sheet
            kwargs["frame"] = item["frame"]
        else:
            source = item["file"] if image is None else image
        kwargs.update(center=item["center"], width=item["width"], height=item["height"])
        if item["angle"]:
            kwargs["angle"] = item["angle"]
        return "Sprite", (source,), kwargs, {}
    raise AssertionError(kind)


def _code_value(value: Any) -> str:
    if isinstance(value, SheetVar):
        return value.name
    if isinstance(value, float):
        value = _plain(value)
    if isinstance(value, (list, tuple)):
        inner = ", ".join(_code_value(v) for v in value)
        return f"({inner})" if isinstance(value, tuple) else f"[{inner}]"
    return repr(value)


def code_for(item: Dict[str, Any], *, var: Optional[str] = None) -> str:
    """Python that makes ``item`` as drawn — the editor's Copy as code.

    One constructor line, plus one assignment line when the class has no
    keyword for a setting (a rotated image). ``var`` names the result; it
    defaults to the item's name when that is a Python identifier.
    """
    cls, args, kwargs, settings = constructor_for(item)
    parts = [_code_value(a) for a in args]
    parts += [f"{k}={_code_value(v)}" for k, v in kwargs.items()]
    groups = item.get("groups", ())
    if groups:
        parts.append("group=" + (repr(groups[0]) if len(groups) == 1 else repr(list(groups))))
    call = f"{cls}({', '.join(parts)})"
    name = var if var is not None else item.get("name")
    if not (isinstance(name, str) and name.isidentifier()):
        name = None
    if settings:
        name = name or cls.lower()
    lines = [f"{name} = {call}" if name else call]
    for attr, value in settings.items():
        lines.append(f"{name}.{attr} = {_code_value(value)}")
    return "\n".join(lines)


def sheet_call(entry: Dict[str, Any], *, file: Optional[str] = None,
               atlas: Optional[str] = None) -> Tuple[tuple, Dict[str, Any]]:
    """``(args, kwargs)`` of the ``Sheet`` a sheet entry describes.

    ``file`` / ``atlas`` are the paths to pass (absolute in ``Level``; as the
    file writes them for Copy as code)."""
    args = (entry["file"] if file is None else file,)
    if entry["cols"] is not None:
        kwargs: Dict[str, Any] = {"cols": entry["cols"]}
        if entry["rows"] is not None:
            kwargs["rows"] = entry["rows"]
    elif entry["cell"] is not None:
        kwargs = {"cell": tuple(entry["cell"])}
    else:
        kwargs = {"atlas": entry["atlas"] if atlas is None else atlas}
    return args, kwargs


def code_for_sheet(entry: Dict[str, Any]) -> str:
    """``terreno = Sheet("tiles.png", cell=(16, 16))`` — a sheet's Copy-as-code line."""
    args, kwargs = sheet_call(entry)
    parts = [_code_value(a) for a in args] + [f"{k}={_code_value(v)}" for k, v in kwargs.items()]
    return f"{entry['name']} = Sheet({', '.join(parts)})"


def code_for_items(items: List[Dict[str, Any]], sheets: List[Dict[str, Any]]) -> str:
    """Copy as code for several items: the ``Sheet`` lines their frames need
    (once each, in first-use order), then one block per item."""
    by_name = {e["name"]: e for e in sheets}
    used: Dict[str, None] = {}
    for item in items:
        if item.get("sheet") is not None:
            used.setdefault(item["sheet"], None)
    lines = [code_for_sheet(by_name[name]) for name in used]
    lines += [code_for(item) for item in items]
    return "\n".join(lines)
