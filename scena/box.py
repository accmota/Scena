"""Measuring ``Box`` / ``Grid`` — layout regions that are not registered Graphics.

Architecture (option d): ``Box`` is a ``Container`` with the same oriented-rect
geometry as ``Rect`` (constructors, corners, angle, links). It never draws,
never joins a layer, and is not an ``Entity``. Layout verbs: ``inset`` /
``outset`` / ``grid`` / ``beside`` / ``strip``.
"""
from __future__ import annotations

import inspect
import math
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

from .state import (
    Container,
    ContainerSlot,
    FieldType,
    ScalarSlot,
    _init_composite,
    _init_scalar,
    batch_update_attrs,
)
from .scenamath import Vec2
from .validate import HINT_EXTENT, magnitude
from .closed import ClosedSurface, seal

# Geometry helpers live on shapes; imported here so Rect and Box share one math.
from .shapes import (
    Point,
    Rect,
    RectModel,
    _RECT_SPINE_ANCHORS,
    _RectFrame,
    _RectNames,
    _bare_num,
    _deg,
    _ensure_writable,
    _finite_deg,
    _rad,
    _rotate_xy,
    _scale_xy,
    get_xy,
)

__all__ = [
    "Box",
    "Grid",
    "region_frame",
    "apply_box_to_shape_kwargs",
    "box_from_graphic",
    "parse_gap",
]



_LAYOUT_SIDES = frozenset({"left", "right", "top", "bottom"})

_GEO_KEYS = frozenset({
    "p1", "p2", "top_left", "center", "width", "height", "vec", "angle", "anchor",
})


def _require_layout_side(side: str) -> str:
    s = str(side)
    if s not in _LAYOUT_SIDES:
        raise ValueError(
            f"side must be one of {sorted(_LAYOUT_SIDES)}, got {side!r}"
        )
    return s

_FORBIDDEN_BOX_KW = frozenset({"color", "layer", "group", "visual"})

# Same construction models as Rect (one table, _RectFrame._init_model).
_CONSTRUCTOR_SIGNATURES = Rect._CONSTRUCTOR_SIGNATURES

_FILL_MIX_KEYS = frozenset({
    "center", "width", "height", "angle", "p1", "p2", "top_left", "vec",
    "anchor", "from_rect", "fp1", "fp2", "major_axis", "padding",
    "perimeter_point", "vertex", "side",
})

_FRAME_GRAPHIC_NAMES = frozenset({
    "Rect", "Square", "Ellipse", "Circle", "Sprite", "Svg", "Text",
})


# ---------------------------------------------------------------------------
# Shared oriented-rect math (used by Box; Rect keeps an equivalent method)
# ---------------------------------------------------------------------------

def oriented_xy(cx: float, cy: float, lx: float, ly: float, ang: float) -> Tuple[float, float]:
    """World point from local (lx, ly) offset about (cx, cy), angle in degrees."""
    rad = math.radians(float(ang))
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    return (cx + lx * cos_a - ly * sin_a, cy + lx * sin_a + ly * cos_a)


def point_in_oriented_rect(
    x: float, y: float,
    cx: float, cy: float, w: float, h: float, ang: float,
) -> bool:
    if w == 0.0 or h == 0.0:
        return False
    dx = x - cx
    dy = y - cy
    if ang:
        rad = math.radians(float(-ang))
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        lx = dx * cos_a - dy * sin_a
        ly = dx * sin_a + dy * cos_a
    else:
        lx, ly = dx, dy
    return abs(lx) <= w / 2.0 and abs(ly) <= h / 2.0


def parse_gap(gap: Any) -> Tuple[float, float]:
    """``gap=16`` or ``gap=(gx, gy)``. Default caller passes 0."""
    if gap is None:
        return 0.0, 0.0
    if isinstance(gap, (int, float)) and not isinstance(gap, bool):
        g = float(gap)
        if g < 0.0:
            raise ValueError(f"gap must be >= 0, got {g}")
        return g, g
    if isinstance(gap, (tuple, list)) and len(gap) == 2:
        gx, gy = float(gap[0]), float(gap[1])
        if gx < 0.0 or gy < 0.0:
            raise ValueError(f"gap components must be >= 0, got {gap!r}")
        return gx, gy
    raise TypeError(
        "gap= expects a number or (gap_x, gap_y) tuple, "
        f"got {type(gap).__name__}"
    )


def _xy_of_point(obj: Any) -> Tuple[float, float]:
    from .shapes import _xy_of
    return _xy_of(obj, required=True)


def frame_kind(obj) -> str:
    """Kind name for the frame dispatch: the Sprite family reads as ``"Sprite"``."""
    from .entity import is_sprite_family, scena_kind
    return "Sprite" if is_sprite_family(obj) else scena_kind(obj)


def region_frame(obj) -> Tuple[float, float, float, float, float]:
    """Return ``(cx, cy, w, h, ang)`` from a Box, Rect, or frame-like Graphic."""
    if obj is None:
        raise TypeError("box= requires a Box, Rect, or frame-like Graphic")
    if isinstance(obj, Box):
        return obj._oriented_frame()
    # A linked angle / scale is pulled before the frame is measured (``.box``,
    # ``confine``, ``box=`` placement: review 2026-10-09 W-G3 / X-writers-5).
    d = getattr(obj, "__dict__", None)
    if d and d.get("_field_anchors"):
        pull = getattr(type(obj), "_pull_property_anchors", None)
        if pull is not None:
            pull(obj)
    name = frame_kind(obj)
    oriented = getattr(obj, "_oriented_frame", None)
    if callable(oriented) and name in ("Rect", "Square"):
        return oriented()
    if name == "Ellipse":
        # The cold reader (Defining inputs only). Reading the public Derivates
        # warmed them, and on a destroyed focal ellipse each read built one
        # more part before raising, then returned a 0 × 0 box (GR3).
        cx, cy, w, h, _ang = obj._oriented_frame()
        return (cx, cy, w, h, obj._rotation_value())
    if name == "Circle":
        # The circle's frame: the diameter square turned to its rim point p1,
        # so ``circle.box.right_center`` is ``circle.p1`` (Named points).
        cx, cy = obj._center_xy()
        r = abs(float(obj._radius_value()))
        return (cx, cy, 2.0 * r, 2.0 * r, obj._rim_heading())
    if name == "Sprite":
        # The drawn rect: pivot, offset, flip and scale applied. ``center`` is
        # the pivot, not the middle of the drawing (anchor="bottom" puts it
        # at the feet), so a box built on it sat half a height low, and
        # ``width`` / ``height`` ignored ``scale``. The angle stays the
        # heading (``angle``, 180 − θ after a flip): the same region as
        # the drawn angle (they differ by 180°), and the frame the box's
        # names are read in (``region_name_signs``).
        cx, cy, w, h, _drawn = obj._oriented_frame()
        return (cx, cy, w, h, float(obj.angle))
    if name == "Text":
        # The layout box (width= or the string), scaled and turned about center.
        obj._refresh_layout()
        cx, cy = get_xy(obj.center, bare=True)
        sc = abs(float(getattr(obj, "_scale", 1.0)))
        w = (obj._x2 - obj._x1) * sc
        h = (obj._y2 - obj._y1) * sc
        ang = float(getattr(obj, "_rotation", 0.0) or 0.0)
        return (cx, cy, w, h, ang)
    raise TypeError(
        f"box= / .box supports Box, Rect, Square, Ellipse, Circle, Sprite, Svg, "
        f"Text; got {type(obj).__name__}"
    )


def region_name_signs(obj) -> Tuple[int, int]:
    """The name signs a region carries into a Box made from it (Named points).

    A Box made from a Graphic is that Graphic's frame, names included:
    ``rect.box.top_right`` is ``rect.top_right``, a flipped sprite's
    ``box.top_center`` is still over its head. Box / Rect / Square keep their
    own names. Sprite / Svg / Ellipse turn their heading on a flip (``180 − θ``
    / ``−θ``) and draw the mirror, which in that frame is one flipped local y
    per flip (Circle too: its frame is turned to its rim point). Text cannot be
    flipped.
    """
    names = getattr(obj, "_effective_name_signs", None)
    if callable(names):
        return names()
    fx = bool(getattr(obj, "_flip_x", False))
    fy = bool(getattr(obj, "_flip_y", False))
    kind = frame_kind(obj)
    if kind in ("Sprite", "Ellipse", "Circle"):
        return (1, -1 if fx != fy else 1)
    return (1, 1)


def box_from_graphic(graphic) -> "Box":
    """Fresh snapshot Box from a frame-like Graphic (``graphic.box``).

    A snapshot of the frame *and* its names — see ``region_name_signs``. The
    screen-aligned edges are ``left`` / ``bottom`` / ``right`` / ``top``.
    """
    name = type(graphic).__name__
    if frame_kind(graphic) not in _FRAME_GRAPHIC_NAMES:
        raise TypeError(
            f"{name}.box is unsupported — Box needs a rectangular frame. "
            "Use Rect, Square, Ellipse, Circle, Sprite, Svg, or Text."
        )
    cx, cy, w, h, ang = region_frame(graphic)
    return Box._snapshot(cx, cy, w, h, ang, name_signs=region_name_signs(graphic))


def apply_box_to_shape_kwargs(
    cls_name: str,
    kwargs: Dict[str, Any],
    *,
    family: str,
    size_keys: Sequence[str] = (),
    heading: bool = False,
) -> Optional[Tuple[int, int]]:
    """Consume ``box=`` and inject pose/size keys. Mutates ``kwargs``.

    Returns the region's name signs (``region_name_signs``) so a Rect /
    Square placed by ``box=`` takes the region's names, or ``None`` when
    there is no ``box=``. ``heading``: an inscribed kind whose ``angle`` is
    a model input (RegularPolygon / Triangle and their subclasses) takes the
    region's angle.
    """
    if "box" not in kwargs:
        return None
    region = kwargs.pop("box")
    size_keyset = frozenset(size_keys)
    mixed = sorted(k for k in kwargs if k in _FILL_MIX_KEYS and k not in size_keyset)
    if mixed:
        raise TypeError(
            f"{cls_name}(box=) cannot mix with {', '.join(mixed)} — "
            "box= is its own constructor family"
        )
    cx, cy, w, h, ang = region_frame(region)
    names = region_name_signs(region)
    size_present = [k for k in size_keys if k in kwargs]
    kwargs.setdefault("center", (cx, cy))
    if family == "fill":
        if size_present:
            raise TypeError(
                f"{cls_name}(box=) fills the region — do not pass "
                f"{', '.join(size_present)}. Use inset() for breathing room."
            )
        kwargs.setdefault("width", w)
        kwargs.setdefault("height", h)
        kwargs.setdefault("angle", ang)
        return names
    if family == "inscribe":
        if size_present:
            return names
        side = min(w, h)
        if "length" in size_keyset:
            kwargs.setdefault("length", side)
            kwargs.setdefault("angle", ang)
        else:
            kwargs.setdefault("radius", side * 0.5)
            if heading:
                kwargs.setdefault("angle", ang)
        return names
    raise ValueError(f"unknown box= family {family!r}")


def sprite_size_from_box(
    region,
    px_w: float,
    px_h: float,
    *,
    width: Any,
    height: Any,
    size: Any,
) -> Tuple[Optional[float], Optional[float], Optional[float], Tuple[float, float], float]:
    """Return ``(width, height, size, center_xy, angle)`` for Sprite ``box=``.

    Author size kwargs win (center only). Otherwise uniform fit inside the region.
    """
    cx, cy, rw, rh, ang = region_frame(region)
    has_size = width is not None or height is not None or size is not None
    if has_size:
        return width, height, size, (cx, cy), 0.0
    aspect = (px_w / px_h) if px_h > 0 else 1.0
    if rw <= 0.0 or rh <= 0.0:
        # Degenerate region: pin at center, size 0 (no crash, no warn).
        return 0.0, 0.0, None, (cx, cy), ang
    # Contain: largest box of the sprite aspect that fits inside the region.
    if rw / rh > aspect:
        fit_h = rh
        fit_w = fit_h * aspect
    else:
        fit_w = rw
        fit_h = fit_w / aspect
    return fit_w, fit_h, None, (cx, cy), ang


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

def _cell_index(value, what: str) -> int:
    """A grid index: a whole number (``2`` or ``2.0``), not a truncated
    ``1.7`` and not ``None`` (A9)."""
    from .state import as_payload
    raw = as_payload(value)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"{what} expected a whole number, got {type(raw).__name__} {raw!r}")
    if isinstance(raw, float) and not raw.is_integer():
        raise TypeError(f"{what} expected a whole number, got {raw!r}")
    return int(raw)

class Grid(ClosedSurface):
    """Division of a Box into cells. Multi-mode accessor — not a container.

    Args:
        parent: The Box to divide.
        cols: Number of columns (>= 1).
        rows: Number of rows (>= 1).
        gap: Space between cells: a number or ``(gx, gy)``.
    """

    def __init__(
        self,
        parent: "Box",
        cols: int,
        rows: int,
        gap: Any = 0,
    ) -> None:
        cols = int(cols)
        rows = int(rows)
        if cols < 1 or rows < 1:
            raise ValueError(f"grid cols and rows must be >= 1, got {cols}, {rows}")
        gap_x, gap_y = parse_gap(gap)
        cx, cy, w, h, ang = parent._oriented_frame()
        # Cells run from the named left / top edges and keep the parent's names.
        self._sa, self._sb = parent._effective_name_signs()
        usable_w = w - gap_x * (cols - 1)
        usable_h = h - gap_y * (rows - 1)
        self._col_count = cols
        self._row_count = rows
        self._gap_x = gap_x
        self._gap_y = gap_y
        self._cx, self._cy, self._w, self._h, self._ang = cx, cy, w, h, ang
        # Remainder: unsatisfiable gap → zero-size cells, same placement math.
        self._cell_w = max(0.0, usable_w / cols)
        self._cell_h = max(0.0, usable_h / rows)
        self._cells: List[Box] = []
        for row in range(rows):
            for col in range(cols):
                self._cells.append(self._make_cell(col, row))

    def _local_cell(self, col: int, row: int) -> Tuple[float, float, float, float]:
        cw, ch = self._cell_w, self._cell_h
        lx = self._sa * (-self._w / 2.0 + cw / 2.0 + col * (cw + self._gap_x))
        ly = self._sb * (self._h / 2.0 - ch / 2.0 - row * (ch + self._gap_y))
        return lx, ly, cw, ch

    def _make_cell(self, col: int, row: int) -> "Box":
        lx, ly, cw, ch = self._local_cell(col, row)
        wx, wy = oriented_xy(self._cx, self._cy, lx, ly, self._ang)
        cell = Box._snapshot(wx, wy, cw, ch, self._ang, name_signs=(self._sa, self._sb))
        cell.col_index = col
        cell.row_index = row
        return cell

    @property
    def col_count(self) -> int:
        """Number of columns. Read-only."""
        return self._col_count

    @property
    def row_count(self) -> int:
        """Number of rows. Read-only."""
        return self._row_count

    @property
    def rows(self) -> List[List["Box"]]:
        """The cells as a list of rows (row 0 is the named top edge), each a list of Boxes."""
        cols = self._col_count
        out: List[List[Box]] = []
        for row in range(self._row_count):
            start = row * cols
            out.append(list(self._cells[start:start + cols]))
        return out

    @property
    def cols(self) -> List[List["Box"]]:
        """The cells as a list of columns (column 0 is the left), each a list of Boxes."""
        rows = self._row_count
        n_cols = self._col_count
        out: List[List[Box]] = []
        for col in range(n_cols):
            out.append([self._cells[row * n_cols + col] for row in range(rows)])
        return out

    def cell(self, a: int, b: Optional[int] = None) -> "Box":
        """``cell(col, row)`` (col-major ≡ (x, y)) or ``cell(n)`` flat index."""
        if b is None:
            n = _cell_index(a, "cell")
            total = self._col_count * self._row_count
            if n < 0 or n >= total:
                raise IndexError(
                    f"cell({n}) out of range — grid has {total} cells "
                    f"({self._col_count}×{self._row_count})"
                )
            col = n % self._col_count
            row = n // self._col_count
            return self._cells[row * self._col_count + col]
        col, row = _cell_index(a, "cell col"), _cell_index(b, "cell row")
        if col < 0 or col >= self._col_count or row < 0 or row >= self._row_count:
            raise IndexError(
                f"cell({col}, {row}) out of range — "
                f"col 0..{self._col_count - 1}, row 0..{self._row_count - 1}"
            )
        return self._cells[row * self._col_count + col]

    def cell_at(self, x: Any, y: Any = None) -> Optional["Box"]:
        """Cell under a world/view point, or ``None``. Oriented: local frame first."""
        if y is None:
            px, py = _xy_of_point(x)
        else:
            from .validate import number
            px, py = number(x, "cell_at x"), number(y, "cell_at y")
        dx = px - self._cx
        dy = py - self._cy
        ang = self._ang
        if ang:
            rad = math.radians(float(-ang))
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            lx = dx * cos_a - dy * sin_a
            ly = dx * sin_a + dy * cos_a
        else:
            lx, ly = dx, dy
        hw, hh = self._w / 2.0, self._h / 2.0
        if lx < -hw or lx > hw or ly < -hh or ly > hh:
            return None
        x_from_left = self._sa * lx + hw
        y_from_top = hh - self._sb * ly
        col = self._index_along(x_from_left, self._col_count, self._cell_w, self._gap_x)
        row = self._index_along(y_from_top, self._row_count, self._cell_h, self._gap_y)
        if col is None or row is None:
            return None
        return self.cell(col, row)

    @staticmethod
    def _index_along(pos: float, count: int, cell: float, gap: float) -> Optional[int]:
        cursor = 0.0
        for i in range(count):
            if cursor <= pos <= cursor + cell:
                return i
            cursor += cell + gap
        # Right/bottom edge: last cell owns the exact outer bound.
        if count and abs(pos - (cursor - gap)) <= 1e-9:
            return count - 1
        return None

    def __iter__(self) -> Iterator["Box"]:
        return iter(self._cells)

    def __len__(self) -> int:
        return len(self._cells)

    def __getitem__(self, key):
        raise TypeError(
            "Grid does not support g[col, row] yet — use g.cell(col, row)."
        )

    def __repr__(self) -> str:
        return f"Grid({self._col_count}×{self._row_count})"


# ---------------------------------------------------------------------------
# Box
# ---------------------------------------------------------------------------

class _SnapshotCenterSlot(ContainerSlot):
    """``Box.center``: a measured box builds its center Point on first touch.

    ``Box._snapshot`` keeps the center as two floats (``_snap_center``).
    Scalars and every derived corner read ``_oriented_frame``, which answers
    from those floats, so ``graphic.box.width`` never builds a Point. The
    first read or write of ``center`` (``__set__`` reads through here too)
    turns the floats into the real Defining Point.
    """

    def __get__(self, instance, owner):
        if instance is None:
            return self
        pending = instance.__dict__.pop("_snap_center", None)
        container = super().__get__(instance, owner)
        if pending is not None:
            with instance._batch_update():
                _init_composite(container, pending)
        return container


class Box(_RectFrame, _RectNames, ClosedSurface, Container):
    """Oriented measuring rectangle. Not a Shape. Not on a layer.

    Same geometry constructors as ``Rect``. No empty ``Box()``. No color / layer
    / group. Layout: ``inset`` / ``outset`` / ``grid`` / ``beside`` /
    ``strip`` / ``contains_point``.

    Args:
        source: A Graphic or Box to copy the region from (``Box(sprite)``).
        p1: One corner (with ``p2``).
        p2: The opposite corner.
        top_left: Top-left corner (with ``width`` / ``height``).
        center: Center (with ``width`` / ``height``).
        width: Width in design units.
        height: Height in design units.
        vec: From ``p1``, the diagonal as a vector.
        angle: Rotation in degrees.
        anchor: With ``p1`` + ``p2`` + ``height``: how the ends sit — ``"cap"`` ·
            ``"square"`` · ``"side_left"`` · ``"side_right"``.
    """

    # Named points follow Rect's rule (first use, then they stay with their
    # points); layout sides follow the names. See ``shapes._RectNames``.
    _ANGLE_FIELD = "angle"

    p1 = ContainerSlot(Point)
    p2 = ContainerSlot(Point)
    top_left = ContainerSlot(Point)
    top_right = ContainerSlot(Point, FieldType.Derivate)
    bottom_left = ContainerSlot(Point, FieldType.Derivate)
    bottom_right = ContainerSlot(Point, FieldType.Derivate)
    vec = ContainerSlot(Vec2, FieldType.Derivate)
    width = ScalarSlot(magnitude=True, hint=HINT_EXTENT)
    height = ScalarSlot(magnitude=True, hint=HINT_EXTENT)
    angle = ScalarSlot()
    center = _SnapshotCenterSlot(Point, FieldType.Derivate)
    top_center = ContainerSlot(Point, FieldType.Derivate)
    bottom_center = ContainerSlot(Point, FieldType.Derivate)
    left_center = ContainerSlot(Point, FieldType.Derivate)
    right_center = ContainerSlot(Point, FieldType.Derivate)

    _PART_NAMES = (
        "p1", "p2", "top_left", "top_right", "bottom_left", "bottom_right", "vec",
        "width", "height", "angle", "center",
        "top_center", "bottom_center", "left_center", "right_center",
    )

    def __init__(self, *args, **kwargs):
        if args:
            if len(args) == 1 and not kwargs:
                super().__init__()
                self.col_index: Optional[int] = None
                self.row_index: Optional[int] = None
                self._anchor = None
                self._init_from_source(args[0])
                return
            raise TypeError(
                "Box does not take positional geometry (corners vs x, y, w, h). "
                "Use keywords, or Box(graphic) / Box.from_graphic(graphic)."
            )
        if not kwargs:
            raise ValueError(
                "Box() needs a region — there is no default measuring box. "
                "Use Box(center=…, width=…, height=…), canvas.game_view, "
                "or canvas.ui_view."
            )
        forbidden = [k for k in kwargs if k in _FORBIDDEN_BOX_KW]
        if forbidden:
            raise TypeError(
                f"Box has no {', '.join(sorted(forbidden))} — it only measures. "
                "Rect draws; Box measures."
            )
        leftover = {k: kwargs[k] for k in kwargs if k not in _GEO_KEYS}
        if leftover:
            from .validate import reject_unexpected_kwargs
            reject_unexpected_kwargs("Box", leftover, valid=_GEO_KEYS)

        super().__init__()
        self.col_index = None
        self.row_index = None
        self._anchor = None
        signature = self._match_signature(kwargs)
        self._init_model(signature, kwargs)

    __init__.__signature__ = inspect.Signature([
        inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter("source", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None),
        *[
            inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=None)
            for name in (
                "p1", "p2", "top_left", "center", "width", "height", "vec", "angle", "anchor",
            )
        ],
    ])

    @classmethod
    def from_graphic(cls, graphic) -> "Box":
        """Same as ``graphic.box`` — fresh snapshot of a frame-like Graphic."""
        return box_from_graphic(graphic)

    def _init_from_source(self, source) -> None:
        # Box(box) and Box(graphic) both keep the source's names.
        self.__dict__["_name_signs"] = region_name_signs(source)
        if isinstance(source, Box):
            self._init_snapshot(*source._oriented_frame())
            return
        self._init_snapshot(*region_frame(source))

    @classmethod
    def _snapshot(
        cls, cx: float, cy: float, w: float, h: float, ang: float,
        name_signs: Optional[Tuple[int, int]] = None,
    ) -> "Box":
        """A measured box: center + size + angle, no Point built yet.

        ``graphic.box``, layout children and grid cells are measurements an
        author mostly reads as numbers. Building the center Point (a full
        Shape part) cost ~60 µs per box; it now waits for the first touch of
        ``center`` (``_SnapshotCenterSlot``). Same Box, same model
        (``CENTER_WH``), same answers.
        """
        box = cls.__new__(cls)
        super(Box, box).__init__()
        # Plain fields: one dict update, not a closed __setattr__ call each.
        box.__dict__.update(col_index=None, row_index=None, _anchor=None)
        box._init_snapshot(cx, cy, w, h, ang)
        if name_signs is not None:
            box.__dict__["_name_signs"] = name_signs
        seal(box)   # built without __init__: close it here
        return box

    @classmethod
    def _from_aabb(cls, left: float, bottom: float, right: float, top: float) -> "Box":
        """A measured, screen-aligned box over an ordered AABB.

        ``canvas.game_view`` / ``ui_view``, ``group[...].box``, a HUD
        widget's ``box`` and playfield layout copies. Same answers as
        ``Box(p1=(left, bottom), p2=(right, top))`` for every name while
        ``left <= right`` and ``bottom <= top``; lazy like ``graphic.box``.
        """
        return cls._snapshot(
            (left + right) / 2.0, (bottom + top) / 2.0,
            right - left, top - bottom, 0.0,
        )

    def _init_snapshot(self, cx: float, cy: float, w: float, h: float, ang: float) -> None:
        """``center_wh_angle`` with the center kept as floats until touched.

        The part tree also stays off the dependency graph until something
        links into it (``Container._in_deferred_graph_tree``): reading
        ``graphic.box.top_left`` every frame builds a Point, but no graph
        node that only the cyclic GC would free.
        """
        self.__dict__["_graph_deferred"] = True
        self.model = RectModel.CENTER_WH
        self.__dict__["_defining_part_names"] = {"center", "width", "height", "angle"}
        self.__dict__["_snap_center"] = (float(cx), float(cy))
        with self._batch_update():
            _init_scalar(self, "width", w)
            _init_scalar(self, "height", h)
            _init_scalar(self, "angle", ang)
        self._rewire_subtree_structural_edges(upward=None)

    @staticmethod
    def _match_signature(kwargs: Dict[str, Any]) -> str:
        present = set(kwargs.keys()) & _GEO_KEYS
        matched = [
            name for name, keys in _CONSTRUCTOR_SIGNATURES if keys == present
        ]
        if len(matched) == 1:
            return matched[0]
        raise ValueError(
            Box._format_incomplete_signature_error(
                present, _CONSTRUCTOR_SIGNATURES,
                home_keys={"center", "width", "height"},
            )
        )

    def _takein_impl(self, other) -> None:
        """``box << other_box`` / ``box @= other_box``: take the source's model,
        its Defining inputs and its names (a copy is a use; Shapes Design,
        "Named points"). Box had no copy at all: both raised
        NotImplementedError (D20 in Testing Design)."""
        if not isinstance(other, Box):
            raise TypeError(
                f"Box << expected a Box, got {type(other).__name__}. "
                "For a snapshot of a shape's frame use Box(shape) or shape.box."
            )
        self.__dict__['_name_signs'] = other._freeze_names()
        self._adopt_model_of(other)
        self._anchor = getattr(other, "_anchor", None)
        self._take_frame_parts(other)

    def _oriented_frame(self) -> Tuple[float, float, float, float, float]:
        # A measured box keeps its center as floats until touched
        # (``_SnapshotCenterSlot``): read them, never build the Point here.
        pending = self.__dict__.get("_snap_center")
        if pending is not None and self.model == RectModel.CENTER_WH:
            return (
                pending[0], pending[1],
                abs(_bare_num(self.width)), abs(_bare_num(self.height)),
                _bare_num(self.angle),
            )
        return _RectFrame._oriented_frame(self)     # no super() proxy (layout reads this)

    def _aabb(self) -> Tuple[float, float, float, float]:
        cx, cy, w, h, ang = self._oriented_frame()
        hw, hh = w / 2.0, h / 2.0
        corners = [
            oriented_xy(cx, cy, lx, ly, ang)
            for lx, ly in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))
        ]
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def left(self) -> float:
        """Smallest x of the region's axis-aligned bounds (rotation included). Read-only."""
        return self._aabb()[0]

    @property
    def bottom(self) -> float:
        """Smallest y of the region's axis-aligned bounds (y-up). Read-only."""
        return self._aabb()[1]

    @property
    def right(self) -> float:
        """Largest x of the region's axis-aligned bounds. Read-only."""
        return self._aabb()[2]

    @property
    def top(self) -> float:
        """Largest y of the region's axis-aligned bounds. Read-only."""
        return self._aabb()[3]

    def contains_point(self, x, y=None) -> bool:
        """Hit geometry only — Box is not clickable. ``(x, y)`` or a point-like."""
        px, py = _xy_of_point(x if y is None else (x, y))
        cx, cy, w, h, ang = self._oriented_frame()
        return point_in_oriented_rect(px, py, cx, cy, w, h, ang)

    @property
    def is_collapsed(self) -> bool:
        """True when the region has no interior (line or point remainder).

        Same predicate as ``contains_point`` / ``point_in_oriented_rect``:
        at least one oriented extent is ``0``. Silent — Remainder policy.
        """
        _cx, _cy, w, h, _ang = self._oriented_frame()
        return w == 0.0 or h == 0.0

    def inset(self, margin: float) -> "Box":
        """Smaller copy, same center and angle. Does not write playfield ``.pad``.

        Each axis clamps to ``>= 0``. Overshoot is a line (one axis 0) or a
        point (both 0) — not an error. Negative margin still raises.
        """
        from .validate import number
        m = number(margin, "inset margin")
        if m < 0.0:
            raise ValueError(f"inset margin must be >= 0, got {m}")
        cx, cy, w, h, _ang = self._oriented_frame()
        nw = max(0.0, w - 2.0 * m)
        nh = max(0.0, h - 2.0 * m)
        return self._named_child((cx, cy), nw, nh)

    def outset(self, margin: float) -> "Box":
        """Larger copy, same center and angle. Does not write playfield ``.pad``.

        Negative margin still raises. A collapsed source (line / point) grows
        back into a region with interior — the inverse of inset remainder.
        """
        from .validate import number
        m = number(margin, "outset margin")
        if m < 0.0:
            raise ValueError(f"outset margin must be >= 0, got {m}")
        cx, cy, w, h, _ang = self._oriented_frame()
        return self._named_child((cx, cy), w + 2.0 * m, h + 2.0 * m)

    def _named_child(self, center: Tuple[float, float], width: float, height: float) -> "Box":
        """A layout child at this box's angle that keeps its names (a copy)."""
        ang = self._oriented_frame()[4]
        return Box._snapshot(
            center[0], center[1], width, height, ang,
            name_signs=self._effective_name_signs(),
        )

    def grid(self, cols: int, rows: int, gap: Any = 0) -> Grid:
        """Divide this box into ``cols``×``rows`` cells (row 0 = the named top edge)."""
        return Grid(self, cols, rows, gap=gap)

    def beside(
        self,
        side: str,
        *,
        width: Optional[float] = None,
        height: Optional[float] = None,
        gap: float = 0,
    ) -> "Box":
        """Outside neighbor copy, flush to one named edge. Keeps source angle.

        Opposite of ``strip`` (inside band). Omitted ``width`` / ``height``
        inherit from the source; both omitted → same size. ``gap`` is air
        between edges (default 0). Negative size or gap raises. Collapsed
        sources are legal (same-size beside of a line is another line).
        ``"top"`` is the edge through ``top_left`` / ``top_right`` — the
        visual top unless the box's corners crossed after it was named.
        """
        s = _require_layout_side(side)
        cx, cy, w, h, ang = self._oriented_frame()
        nw = float(w if width is None else width)
        nh = float(h if height is None else height)
        g = float(gap)
        if nw < 0.0:
            raise ValueError(f"beside width must be >= 0, got {nw}")
        if nh < 0.0:
            raise ValueError(f"beside height must be >= 0, got {nh}")
        if g < 0.0:
            raise ValueError(f"beside gap must be >= 0, got {g}")
        sa, sb = self._effective_name_signs()
        if s == "right":
            lx, ly = sa * ((w + nw) / 2.0 + g), 0.0
        elif s == "left":
            lx, ly = -sa * ((w + nw) / 2.0 + g), 0.0
        elif s == "top":
            lx, ly = 0.0, sb * ((h + nh) / 2.0 + g)
        else:  # bottom
            lx, ly = 0.0, -sb * ((h + nh) / 2.0 + g)
        return self._named_child(oriented_xy(cx, cy, lx, ly, ang), nw, nh)

    def strip(self, side: str, thickness: float) -> "Box":
        """Inside edge-band copy, flush to one named edge. Keeps source angle.

        Opposite of ``beside`` (outside neighbor). Full span on the long axis;
        ``thickness`` on the short axis. Overshoot clamps to the source extent
        and pins the center as a filled band — Remainder policy, silent.
        Negative thickness raises. Unknown side raises.
        """
        s = _require_layout_side(side)
        t = float(thickness)
        if t < 0.0:
            raise ValueError(f"strip thickness must be >= 0, got {t}")
        cx, cy, w, h, ang = self._oriented_frame()
        sa, sb = self._effective_name_signs()
        if s in ("top", "bottom"):
            nw = w
            nh = max(0.0, min(t, h))
            ly = sb * ((h - nh) / 2.0 if s == "top" else -(h - nh) / 2.0)
            lx = 0.0
        else:  # left / right
            nw = max(0.0, min(t, w))
            nh = h
            lx = sa * (-(w - nw) / 2.0 if s == "left" else (w - nw) / 2.0)
            ly = 0.0
        return self._named_child(oriented_xy(cx, cy, lx, ly, ang), nw, nh)

    def _center_xy(self) -> Tuple[float, float]:
        cx, cy, *_rest = self._oriented_frame()
        return cx, cy

    def _pivot_xy(self, about=None) -> Tuple[float, float]:
        if about is None:
            return self._center_xy()
        from .shapes import _xy_of
        return _xy_of(about, required=True)

    def rotate_to(self, value: float, *, about=None, force: bool = False) -> "Box":
        """Turn the region to ``value`` degrees (absolute). Returns the same Box.

        Args:
            value: target angle in degrees.
            about: pivot point (default: the center).
            force: override a linked angle (unlinks it).
        """
        target = _finite_deg(value, "rotate_to angle")
        current = _bare_num(self.angle)
        return self.rotate_by(target - current, about=about, force=force)

    def rotate_by(self, angle: float, *, about=None, force: bool = False) -> "Box":
        """Turn the region by ``angle`` degrees (relative). Returns the same Box.

        Args:
            angle: degrees to add (counter-clockwise).
            about: pivot point (default: the center).
            force: override a linked angle (unlinks it).
        """
        dθ_deg = _finite_deg(angle, "rotate_by angle")
        if dθ_deg == 0.0:
            return self
        # Rect's body (``_RectFrame._rotate_frame``): one copy, no drift.
        self._rotate_frame(dθ_deg, about=about, force=force)
        return self

    def __repr__(self) -> str:
        cx, cy, w, h, ang = self._oriented_frame()
        extra = ""
        if self.col_index is not None:
            extra = f" col_index={self.col_index} row_index={self.row_index}"
        return (
            f"Box(center=({cx:.3g}, {cy:.3g}), width={w:.3g}, "
            f"height={h:.3g}, angle={ang:.3g}{extra})"
        )
