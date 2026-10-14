"""Level file format (``*.json`` made by the level editor): parse, check, write.

Pure data — no Graphics. ``scena.level.Level`` reads files through
:func:`parse`; the level editor (``scena_editor``) writes them through
:func:`serialize`. :func:`constructor_for` is the one kind → constructor
table: ``LevelItem.make()`` and the editor's "Copy as code" both use it, so
the shape made in code and the line copied from the editor never disagree.

A level file::

    {"format": "scena-level", "version": 1, "size": [3600, 1500],
     "items": [{"kind": "rect", "groups": ["plataforma"], "center": [450, 170],
                "width": 220, "height": 24, "angle": 20}, ...]}

Design units, y up, ``angle`` in degrees counter-clockwise — the same
numbers an author writes in code. ``items`` order is the draw order. See
``design/Editor Design.md``.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .validate import did_you_mean

FORMAT = "scena-level"
VERSION = 1
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
_SCOOP = "scoop"      # a named point of the box (Concave scoop=)
_RIM = "rim"          # a pair [x, y] of numbers >= 0 (Concave rim=)

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
    "track": {"required": {"points": _POINTS},
              "optional": {"closed": (_BOOL, False), "smooth": (_FRACTION, 0.0)}},
    "point": {"required": {"center": _POINT}, "optional": {}},
    "image": {"required": {"file": _TEXT, "center": _POINT, "width": _SIZE, "height": _SIZE},
              "optional": {"angle": (_NUMBER, 0.0), "guide": (_BOOL, False)}},
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
_KEY_ORDER = ("kind", "name", "groups", "file", "center", "p1", "p2", "points",
              "width", "height", "radius", "n", "angle", "scoop", "rim", "closed", "smooth",
              "guide", "locked")


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
    name = raw.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise LevelFormatError(f"{where}: name must be a non-empty string, got {name!r}")
    item["name"] = name
    item["groups"] = _groups(raw.get("groups", ()), f"{where}: groups")
    item["locked"] = _field(_BOOL, raw.get("locked", False), f"{where}: locked")
    return item


def parse(data: Any, *, source: str = "level") -> Dict[str, Any]:
    """A decoded level file → ``{"size": (w, h), "items": [normalized items]}``.

    Raises :class:`LevelFormatError` (a ``ValueError``) naming ``source`` and
    the item, never half-reads a file.
    """
    if not isinstance(data, dict) or (
        data.get("format") != FORMAT and data.get("format") not in LEGACY_FORMATS
    ):
        raise LevelFormatError(
            f"{source} is not a Scena level file (no \"format\": \"{FORMAT}\"). "
            "Level files are made by the level editor: python -m scena_editor"
        )
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise LevelFormatError(f"{source}: version must be a whole number >= 1, got {version!r}")
    if version > VERSION:
        raise LevelFormatError(
            f"{source} was saved by a newer Scena (level version {version}; this "
            f"Scena reads up to {VERSION}). Update Scena."
        )
    for key in data:
        if key not in ("format", "version", "size", "items"):
            raise LevelFormatError(
                f"{source}: unknown top-level key {key!r}. Keys: format, version, size, items."
                + did_you_mean(key, ("format", "version", "size", "items"))
            )
    size = _point(data.get("size"), f"{source}: size")
    if size[0] < 0 or size[1] < 0:
        raise LevelFormatError(f"{source}: size must be >= 0, got {list(size)}")
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
        items.append(item)
    return {"size": size, "items": items}


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


def serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """``{"size": .., "items": [..]}`` (normalized) → a JSON-ready level file dict."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "size": _plain(doc["size"]),
        "items": [serialize_item(item) for item in doc["items"]],
    }


def dumps(data: Dict[str, Any]) -> str:
    """A level file dict (from :func:`serialize`) as text: one item per line,
    so the file reads like a list and diffs line by line."""
    import json
    head = {k: data[k] for k in ("format", "version", "size")}
    out = [json.dumps(head, ensure_ascii=False)[:-1] + ', "items": [']
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

def constructor_for(item: Dict[str, Any], *, image: Optional[str] = None
                    ) -> Tuple[str, tuple, Dict[str, Any], Dict[str, Any]]:
    """``(class name, positional args, keyword args, settings after construction)``.

    ``image`` is the image path to pass (absolute in ``make()``, as written in
    the file for Copy as code). Groups are not included — the caller adds
    ``group=``. ``settings`` holds attributes to assign after construction
    (none today: every kind's fields are constructor keywords).
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
        source = item["file"] if image is None else image
        kwargs = {"center": item["center"], "width": item["width"], "height": item["height"]}
        if item["angle"]:
            kwargs["angle"] = item["angle"]
        return "Sprite", (source,), kwargs, {}
    raise AssertionError(kind)


def _code_value(value: Any) -> str:
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
