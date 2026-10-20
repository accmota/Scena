"""``Level``: read a level file made by the level editor. Creates nothing.

A level file places geometry — rects, ellipses, concaves, circles, lines,
polygons, regular polygons, triangles, tracks, points and images — with
names and groups. Game code reads it and decides what each item becomes::

    fase = Level("fase1.json")
    for p in fase.group("plataforma"):
        bloco = p.make()            # the Rect as drawn, in group "plataforma"
        bloco.mass = STATIC
    heroi.center = fase["inicio"].center

``item.make()`` builds the shape exactly as drawn; ``item.box`` is the region
(for ``Sprite(box=)``, ``confine``, a grid …). Two purposes, not two
spellings. An image item cut from a spritesheet makes ``Sprite(sheet,
frame=…)`` with the level's ``Sheet`` (``level.sheet(name)``, built on first
use). File format and editor: ``design/Editor Design.md``.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .level_format import (
    AREA_KINDS, KINDS, LevelFormatError, constructor_for, parse, sheet_call,
)
from .validate import did_you_mean
from .closed import ClosedSurface

__all__ = ["Level", "LevelItem", "LevelFormatError"]

# Fields each kind answers, beyond kind / name / groups / center / make.
_KIND_FIELDS = {
    "rect": ("box", "width", "height", "angle"),
    "ellipse": ("box", "width", "height", "angle"),
    "concave": ("box", "width", "height", "angle", "scoop", "rim"),
    "circle": ("box", "radius"),
    "line": ("p1", "p2", "length", "angle"),
    "polygon": ("points",),
    "regular_polygon": ("radius", "n", "angle"),
    "triangle": ("radius", "angle", "base_ratio"),
    "track": ("points", "closed", "smooth"),
    "point": (),
    "image": ("box", "image", "sheet", "frame", "width", "height", "angle"),
}
_COMMON_FIELDS = ("kind", "name", "groups", "center", "make")


def _vec(p):
    from .scenamath import Vec2
    return Vec2(p[0], p[1])


class LevelItem:
    """One item of a :class:`Level`: geometry, a name and groups. Not drawn.

    Every item has ``kind``, ``name``, ``groups``, ``center`` and ``make()``.
    The rest depends on the kind — asking a line for ``radius`` raises with
    the fields a line has. Values are copies: changing them does not change
    the level.
    """

    __slots__ = ("_item", "_image", "_source", "_level", "_index")

    def __init__(self, item: Dict[str, Any], *, image: Optional[str] = None, source: str = "",
                 level: Optional["Level"] = None, index: Optional[int] = None):
        """Made by :class:`Level` — read items with ``level["name"]`` or ``level.group("g")``.

        Args:
            item: The checked item record (from ``scena.level_format.parse``).
            image: Absolute path of an image item's file.
            source: The level file, for messages.
            level: The level it belongs to (a frame image gets its ``Sheet`` there).
            index: Its place in the file's items, for messages.
        """
        self._item = item
        self._image = image
        self._source = source
        self._level = level
        self._index = index

    # -- identity -----------------------------------------------------------
    @property
    def kind(self) -> str:
        """``"rect"``, ``"ellipse"``, ``"concave"``, ``"circle"``, ``"line"``,
        ``"polygon"``, ``"regular_polygon"``, ``"triangle"``, ``"track"``, ``"point"`` or
        ``"image"``."""
        return self._item["kind"]

    @property
    def name(self) -> Optional[str]:
        """The name given in the editor, or ``None``. Unique in a level."""
        return self._item["name"]

    @property
    def groups(self) -> Tuple[str, ...]:
        """The item's groups (a tuple, possibly empty). ``make()`` applies them."""
        return tuple(self._item["groups"])

    # -- geometry -----------------------------------------------------------
    def _need(self, field: str) -> None:
        if field not in _KIND_FIELDS[self.kind]:
            has = ", ".join(_COMMON_FIELDS + _KIND_FIELDS[self.kind])
            hint = {
                "box": " Only rects, ellipses, concaves, circles and images are regions (a line,"
                       " polygon, track or point: its points; a regular polygon or a"
                       " triangle: its center and radius).",
            }.get(field, "")
            raise AttributeError(
                f"{self._label()} has no {field}. It has: {has}.{hint}"
            )

    def _label_short(self) -> str:
        return self.kind + (f" {self.name!r}" if self.name else "")

    def _label(self) -> str:
        return f"the {self.kind}" + (f" {self.name!r}" if self.name else "") + (
            f" in {self._source}" if self._source else "")

    @property
    def center(self):
        """Center as a ``Vec2``. Lines: the midpoint; polygons and tracks: the
        middle of their bounding box; points: the point itself."""
        item = self._item
        if "center" in item:
            return _vec(item["center"])
        if self.kind == "line":
            (x1, y1), (x2, y2) = item["p1"], item["p2"]
            return _vec(((x1 + x2) / 2, (y1 + y2) / 2))
        xs = [p[0] for p in item["points"]]
        ys = [p[1] for p in item["points"]]
        return _vec(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))

    @property
    def box(self):
        """The region as a fresh oriented ``Box`` (rect, ellipse, concave, image, circle).

        ``Rect(box=item.box)``, ``Sprite("x.png", box=item.box)``,
        ``hero.confine(item.box)``. A circle's box is the square around it.
        Lines, polygons, tracks and points have no box.
        """
        self._need("box")
        from .box import Box
        item = self._item
        if self.kind == "circle":
            d = 2 * item["radius"]
            return Box(center=item["center"], width=d, height=d)
        return Box(center=item["center"], width=item["width"], height=item["height"],
                   angle=item["angle"])

    @property
    def width(self) -> float:
        """Width in design units (rect, ellipse, concave, image)."""
        self._need("width")
        return self._item["width"]

    @property
    def height(self) -> float:
        """Height in design units (rect, ellipse, concave, image)."""
        self._need("height")
        return self._item["height"]

    @property
    def angle(self) -> float:
        """Angle in degrees, counter-clockwise (rect, ellipse, concave, image; regular_polygon:
        toward its first vertex; triangle: toward its apex) — like ``Graphic.angle``.
        A line's is the direction ``p1 → p2``, as ``item.make().angle`` reads it
        (``-180`` up to ``180``; ``0`` when the ends meet)."""
        self._need("angle")
        if self.kind == "line":
            from .shapes import _unwrap_deg
            (x1, y1), (x2, y2) = self._item["p1"], self._item["p2"]
            if x1 == x2 and y1 == y2:
                return 0.0
            return _unwrap_deg(math.degrees(math.atan2(y2 - y1, x2 - x1)), 0.0)
        return self._item["angle"]

    @property
    def length(self) -> float:
        """Distance from ``p1`` to ``p2`` (line), as ``item.make().length`` reads it.
        With ``angle``, it builds the line in another model:
        ``Line(p1=item.p1, angle=item.angle, length=item.length)``."""
        self._need("length")
        (x1, y1), (x2, y2) = self._item["p1"], self._item["p2"]
        return math.hypot(x2 - x1, y2 - y1)

    @property
    def radius(self) -> float:
        """Radius in design units (circle; regular_polygon: center to a vertex;
        triangle: center to the apex)."""
        self._need("radius")
        return self._item["radius"]

    @property
    def p1(self):
        """First end as a ``Vec2`` (line)."""
        self._need("p1")
        return _vec(self._item["p1"])

    @property
    def p2(self):
        """Second end as a ``Vec2`` (line)."""
        self._need("p2")
        return _vec(self._item["p2"])

    @property
    def points(self) -> list:
        """The points as a new list of ``Vec2`` (polygon, track). A straight
        track's list goes straight to ``move_along``; a smooth one's are its
        control points — ``move_along(item.make())`` follows the curve."""
        self._need("points")
        return [_vec(p) for p in self._item["points"]]

    @property
    def closed(self) -> bool:
        """True when the track loops back to its first point (track)."""
        self._need("closed")
        return self._item["closed"]

    @property
    def n(self) -> int:
        """Number of sides (regular_polygon) — ``RegularPolygon(n=)``."""
        self._need("n")
        return self._item["n"]

    @property
    def base_ratio(self) -> float:
        """Base / side, above 0 and below 2 (triangle; 1 is equilateral) —
        ``Triangle(base_ratio=)``."""
        self._need("base_ratio")
        return self._item["base_ratio"]

    @property
    def scoop(self) -> str:
        """The named point the curve is centered on (concave) — ``Concave(scoop=)``."""
        self._need("scoop")
        return self._item["scoop"]

    @property
    def rim(self):
        """The solid left at the scoop's ends as a ``Vec2`` (concave) — ``Concave(rim=)``."""
        self._need("rim")
        return _vec(self._item["rim"])

    @property
    def smooth(self) -> float:
        """Corner rounding, 0 = straight segments, 1 = a smooth curve (track) —
        ``Track.smooth``."""
        self._need("smooth")
        return self._item["smooth"]

    @property
    def image(self) -> str:
        """Absolute path of the image file (an image with a whole picture). The
        file names it relative to the level file. A frame of a sheet has none:
        ``item.sheet`` and ``item.frame``, or ``item.make()``."""
        self._need("image")
        if self._item["sheet"] is not None:
            raise AttributeError(
                f"{self._label()} is frame {self._item['frame']!r} of the sheet "
                f"{self._item['sheet']!r}, not a whole picture: the sheet's file would show "
                "every frame. Use item.make(), or Sprite(item.sheet, frame=item.frame, …)."
            )
        return self._image

    @property
    def sheet(self):
        """The ``Sheet`` this image's frame is cut from (an image of a sheet) —
        ``level.sheet(name)``: the same catalog for every item of that sheet,
        so a clip registered on it plays on what ``make()`` builds."""
        self._need("sheet")
        name = self._item["sheet"]
        if name is None:
            raise AttributeError(
                f"{self._label()} is a whole picture, not a frame of a sheet: it has "
                "item.image."
            )
        return self._level.sheet(name)

    @property
    def frame(self):
        """The frame's index (a grid) or name (an atlas) in ``item.sheet`` (an
        image of a sheet) — ``Sprite(frame=)``."""
        self._need("frame")
        if self._item["sheet"] is None:
            raise AttributeError(
                f"{self._label()} is a whole picture, not a frame of a sheet: it has "
                "item.image."
            )
        return self._item["frame"]

    # -- make ---------------------------------------------------------------
    def make(self, **kwargs):
        """Create the shape exactly as drawn, in the item's groups.

        rect → ``Rect``, ellipse → ``Ellipse``, concave → ``Concave`` (its
        scoop and rim), circle → ``Circle``,
        line → ``Line``, polygon → ``Polygon``, regular_polygon →
        ``RegularPolygon``, triangle → ``Triangle`` (its ``base_ratio``),
        track → ``Track`` (its
        ``smooth``, 0 when the file has none),
        point → ``Point``, image → ``Sprite`` (that size and angle; a frame of a
        sheet → ``Sprite(item.sheet, frame=item.frame, …)``).
        Other constructor keywords pass through (``layer=``, ``color=``, …);
        ``group=`` adds to the item's groups. Same table as the editor's
        Copy as code.

        Args:
            **kwargs: Constructor keywords for the new shape (``layer=``,
                ``group=``, ``color=``, ``visual=`` …). Geometry comes from the
                item; passing it here raises.
        """
        item = self._item
        if item.get("guide"):
            raise ValueError(
                f"{self._label()} is a guide: the editor shows it for tracing and "
                "the game does not use it."
            )
        sheet = self.sheet if item["kind"] == "image" and item["sheet"] is not None else None
        cls_name, args, base, settings = constructor_for(item, image=self._image, sheet=sheet)
        clash = sorted(set(kwargs) & set(base))
        if clash:
            raise TypeError(
                f"make() takes the geometry from the level ({self._label()}): "
                f"remove {'=, '.join(clash)}=. Change the shape after making it, "
                "or move it in the editor."
            )
        groups = list(item["groups"])
        extra = kwargs.pop("group", None)
        if extra is not None:
            for g in ([extra] if isinstance(extra, str) else list(extra)):
                if g not in groups:
                    groups.append(g)
        if groups:
            kwargs["group"] = groups[0] if len(groups) == 1 else groups
        import sys
        from ._pkg import PKG
        shape = getattr(sys.modules[PKG], cls_name)(*args, **base, **kwargs)
        for attr, value in settings.items():
            setattr(shape, attr, value)
        return shape

    def __repr__(self) -> str:
        label = f" {self.name!r}" if self.name else ""
        groups = f" groups={list(self.groups)}" if self.groups else ""
        return f"<LevelItem {self.kind}{label}{groups}>"


class Level(ClosedSurface):
    """A level file made by the level editor (``python -m scena_editor``).

    Reading only: ``Level("fase1.json")`` creates nothing on screen. Find
    items by name (``level["elevador"]``) or by group
    (``level.group("plataforma")``) and decide in code what each becomes —
    ``item.make()`` for the shape as drawn, ``item.box`` / ``item.center`` /
    ``item.points`` for the geometry. Guide images (editor-only tracing
    references) are not part of the level.
    """

    def __init__(self, path: str):
        """Read a level file.

        Args:
            path: The ``.json`` file. A relative path is looked up next to the
                running script, then in its ``media/`` folder, then in the
                current folder (the same as Sprite images).
        """
        from .sprite import _resolve_image_path, _script_dir
        if not isinstance(path, (str, os.PathLike)):
            raise TypeError(
                f"Level expected a file path such as \"fase1.json\", got {type(path).__name__}"
            )
        path = os.fspath(path)
        found = _resolve_image_path(path)
        if found is None:
            where = [d for d in (_script_dir(), os.getcwd()) if d]
            raise ValueError(
                f"Level file not found: {path!r}. Looked next to the script, in its "
                f"media/ folder and in the current folder ({', '.join(where)})."
            )
        self._path = found
        label = os.path.basename(found)
        try:
            with open(found, encoding="utf-8-sig") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise LevelFormatError(
                f"{label} is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}"
            ) from None
        doc = parse(data, source=label)
        self._size = doc["size"]
        base = os.path.dirname(found)

        def absolute(file: str) -> str:
            # Relative to the level file (POSIX separators). The editor
            # writes an absolute path only when no relative one exists
            # (another drive on Windows).
            return (os.path.normpath(file) if os.path.isabs(file)
                    else os.path.normpath(os.path.join(base, *file.split("/"))))

        self._sheet_entries: Dict[str, Dict[str, Any]] = {}
        for entry in doc["sheets"]:
            entry = dict(entry, file=absolute(entry["file"]))
            if entry["atlas"] is not None:
                entry["atlas"] = absolute(entry["atlas"])
            self._sheet_entries[entry["name"]] = entry
        self._sheets: Dict[str, Any] = {}
        self._items: List[LevelItem] = []
        for index, item in enumerate(doc["items"]):
            if item.get("guide"):
                continue
            image = None
            if item["kind"] == "image" and item["file"] is not None:
                image = absolute(item["file"])
            self._items.append(LevelItem(item, image=image, source=label, level=self, index=index))
        self._by_name = {it.name: it for it in self._items if it.name is not None}
        self._label = label

    @property
    def path(self) -> str:
        """Absolute path of the file that was read."""
        return self._path

    @property
    def sheets(self) -> Tuple[str, ...]:
        """Every sheet name in the file's ``sheets`` table, in file order."""
        return tuple(self._sheet_entries)

    def sheet(self, name: str):
        """The ``Sheet`` named ``name`` in the level's ``sheets`` table.

        Built on first use (the default anchor) and kept: every frame image of
        that sheet — ``item.sheet``, ``item.make()`` — uses this one catalog, so
        a clip registered here plays on them
        (``level.sheet("agua").clip("onda", [40, 41, 42], fps=6)``). Building it
        checks the frame of every item cut from it: an unknown frame raises
        ``LevelFormatError`` naming the item. A missing image or atlas file
        shows a placeholder, as for any image.

        Args:
            name: A sheet name from the level file (``"terreno"``).
        """
        if not isinstance(name, str):
            raise TypeError(f"level.sheet expected a sheet name, got {type(name).__name__}")
        sheet = self._sheets.get(name)
        if sheet is not None:
            return sheet
        entry = self._sheet_entries.get(name)
        if entry is None:
            known = self.sheets
            raise ValueError(
                f"{self._label} has no sheet named {name!r}."
                + (did_you_mean(name, known) or (
                    f" Sheets: {', '.join(known)}." if known else " The level has no sheets."))
            )
        from .sprite import Sheet
        args, kwargs = sheet_call(entry)
        sheet = Sheet(*args, **kwargs)
        for it in self._items:
            if it._item["kind"] != "image" or it._item["sheet"] != name:
                continue
            try:
                sheet.frame_index(it._item["frame"])
            except (ValueError, TypeError) as e:
                raise LevelFormatError(
                    f"{self._label}: item {it._index} ({it._label_short()}): the sheet {name!r} "
                    f"has no frame {it._item['frame']!r}. {e}"
                ) from None
        self._sheets[name] = sheet
        return sheet

    @property
    def size(self) -> Tuple[float, float]:
        """``(width, height)`` of the level area, set in the editor."""
        return tuple(self._size)

    @property
    def box(self):
        """The level area as a fresh ``Box`` from ``(0, 0)`` to ``size`` —
        for ``canvas.playfield``, camera limits, ``confine``."""
        from .box import Box
        w, h = self._size
        return Box(center=(w / 2, h / 2), width=w, height=h)

    @property
    def names(self) -> Tuple[str, ...]:
        """Every item name, in file order."""
        return tuple(self._by_name)

    @property
    def groups(self) -> Tuple[str, ...]:
        """Every group used by some item, in order of first use."""
        seen: Dict[str, None] = {}
        for it in self._items:
            for g in it.groups:
                seen.setdefault(g, None)
        return tuple(seen)

    def group(self, name: str) -> List[LevelItem]:
        """The items in group ``name``, in file (draw) order.

        Raises when no item has that group — a typo would otherwise give an
        empty list and a level with something missing.

        Args:
            name: A group given in the editor (``"plataforma"``).
        """
        if not isinstance(name, str):
            raise TypeError(f"level.group expected a group name, got {type(name).__name__}")
        found = [it for it in self._items if name in it._item["groups"]]
        if not found:
            known = self.groups
            raise ValueError(
                f"{self._label} has no item in group {name!r}."
                + (did_you_mean(name, known) or (
                    f" Groups: {', '.join(known)}." if known else " No item has a group."))
            )
        return found

    def __getitem__(self, name: str) -> LevelItem:
        """The item named ``name`` (``level["elevador"]``)."""
        if not isinstance(name, str):
            raise TypeError(
                f"level[...] takes an item name such as level[\"inicio\"], got "
                f"{type(name).__name__}. For a group: level.group(\"plataforma\")."
            )
        item = self._by_name.get(name)
        if item is None:
            hint = did_you_mean(name, self._by_name)
            if not hint and name in self.groups:
                hint = f" {name!r} is a group: level.group({name!r})."
            raise ValueError(f"{self._label} has no item named {name!r}." + (
                hint or (f" Names: {', '.join(self._by_name)}." if self._by_name else "")))
        return item

    def __contains__(self, name: object) -> bool:
        """``"inicio" in level`` — True when an item has that name."""
        return name in self._by_name

    def __iter__(self) -> Iterator[LevelItem]:
        """Every item, in file (draw) order."""
        return iter(list(self._items))

    def __len__(self) -> int:
        """How many items (guides excluded)."""
        return len(self._items)

    def __repr__(self) -> str:
        return f"<Level {self._label} {self._size[0]:g}x{self._size[1]:g}, {len(self._items)} items>"
