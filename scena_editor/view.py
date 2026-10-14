"""Draw the document with Scena: items, selection, handles, grid, level frame.

``LevelView.sync(editor)`` runs every frame and changes Graphics only when the
document, the selection or the zoom changed. All editor Graphics are plain
(not draggable / clickable), so every pointer event reaches the script
callbacks and ``Editor`` decides (Editor Design.md — Spike lessons).

``ScenaViewport`` is the ``Viewport`` the controller pans and zooms through
(public canvas API only).
"""
from __future__ import annotations

import math
import zlib
from typing import Any, Dict, List, Optional, Tuple

from scena import (
    Circle, Color, Ellipse, Line, Polygon, Rect, RegularPolygon, Sprite, Track, canvas,
)

from . import geometry as geo
from .tools import HANDLE_PX, Editor

DESIGN = (1280.0, 800.0)
# Screen areas the panels cover (view units, y up): left, right, bottom, top.
PANEL_LEFT, PANEL_RIGHT, PANEL_BOTTOM, PANEL_TOP = 74.0, 270.0, 28.0, 44.0
BG_LAYER, ITEM_LAYER, OVERLAY_LAYER = "editor_bg", "default", "top"
ZOOM_MIN, ZOOM_MAX = 0.05, 20.0
GRID_MIN_PX = 8.0           # lines closer than this on screen are thinned
MAX_GRID_LINES = 260
POINT_RING_PX = 11.0

PALETTE = ("light sky blue", "light green", "sandy brown", "plum", "light coral",
           "turquoise", "khaki", "light steel blue")
UNGROUPED = "silver"
SELECTED = "gold"


def group_color(groups) -> Color:
    if not groups:
        return Color(UNGROUPED)
    return Color(PALETTE[zlib.crc32(groups[0].encode("utf-8")) % len(PALETTE)])


def translucent(color: Color, alpha: float) -> Color:
    r, g, b, _a = color.rgb
    return Color(r, g, b, alpha)


def view_point(x: float, y: float) -> Tuple[float, float]:
    """World → view (design-window) coordinates through the public camera."""
    z = canvas.zoom
    return ((x - canvas.pan_x) * z + DESIGN[0] / 2, (y - canvas.pan_y) * z + DESIGN[1] / 2)


def over_panel(x: float, y: float) -> bool:
    """Is the world point ``(x, y)`` under a panel on screen?"""
    vx, vy = view_point(x, y)
    return (vx < PANEL_LEFT or vx > DESIGN[0] - PANEL_RIGHT
            or vy < PANEL_BOTTOM or vy > DESIGN[1] - PANEL_TOP)


class ScenaViewport:
    """The editor camera on Scena's canvas. ``pan_by`` moves the content."""

    @property
    def zoom(self) -> float:
        return canvas.zoom

    def pan_by(self, dx: float, dy: float) -> None:
        canvas.pan_by(dx, dy)

    def zoom_about(self, factor: float, x: float, y: float) -> None:
        z = min(max(canvas.zoom * factor, ZOOM_MIN), ZOOM_MAX)
        if z != canvas.zoom:
            canvas.zoom_by(z / canvas.zoom, about=(x, y))

    def _show(self, cx: float, cy: float, zoom: float) -> None:
        """World point (cx, cy) at the middle of the canvas area between panels."""
        zoom = min(max(zoom, ZOOM_MIN), ZOOM_MAX)
        canvas.zoom_to(zoom)
        mid_vx = (PANEL_LEFT + DESIGN[0] - PANEL_RIGHT) / 2
        mid_vy = (PANEL_BOTTOM + DESIGN[1] - PANEL_TOP) / 2
        canvas.pan_to(cx - (mid_vx - DESIGN[0] / 2) / zoom, cy - (mid_vy - DESIGN[1] / 2) / zoom)

    def fit(self, box) -> None:
        x0, y0, x1, y1 = box
        w = max(x1 - x0, 1.0)
        h = max(y1 - y0, 1.0)
        avail_w = DESIGN[0] - PANEL_LEFT - PANEL_RIGHT
        avail_h = DESIGN[1] - PANEL_BOTTOM - PANEL_TOP
        self._show((x0 + x1) / 2, (y0 + y1) / 2, 0.92 * min(avail_w / w, avail_h / h))

    def actual_size(self) -> None:
        """Zoom 100% about the middle of the canvas area (between the panels)."""
        mid_vx = (PANEL_LEFT + DESIGN[0] - PANEL_RIGHT) / 2
        mid_vy = (PANEL_BOTTOM + DESIGN[1] - PANEL_TOP) / 2
        z = canvas.zoom
        cx = (mid_vx - DESIGN[0] / 2) / z + canvas.pan_x
        cy = (mid_vy - DESIGN[1] / 2) / z + canvas.pan_y
        self._show(cx, cy, 1.0)


class _ItemView:
    __slots__ = ("shape", "key", "item")

    def __init__(self, shape, key, item):
        self.shape, self.key, self.item = shape, key, item


class LevelView:
    def __init__(self):
        if BG_LAYER not in canvas.layers:
            canvas.layers.create(BG_LAYER, below=ITEM_LAYER)
        self.items: Dict[int, _ItemView] = {}
        self._order: List[int] = []
        self._seen = None                       # (doc version, selection, zoom, base dir)
        self.frame = Rect(center=(0, 0), width=1, height=1, layer=BG_LAYER)
        self.frame.fill = Color(1, 1, 1, 0.035)
        self.frame.line = "gray"
        self._grid_lines: List[Line] = []
        self._grid_key = None
        self._handles: List[Rect] = []
        self._rotate_knob = Circle(center=(0, 0), radius=4, layer=OVERLAY_LAYER)
        self._rotate_knob.fill = SELECTED
        self._rotate_knob.line = "black"
        self._rotate_knob.visible = False
        # A group selection's frame: the box its corner handles and knob belong to.
        self._group_frame = Rect(center=(0, 0), width=1, height=1, layer=OVERLAY_LAYER)
        self._group_frame.fill = None
        self._group_frame.line = SELECTED
        self._group_frame.visible = False
        self._band = Rect(center=(0, 0), width=1, height=1, layer=OVERLAY_LAYER)
        self._band.fill = Color(1, 0.85, 0.3, 0.12)
        self._band.line = SELECTED
        self._band.visible = False
        self._pending: List[Line] = []
        self._image_marks: List[Rect] = []      # outlines of selected images
        self._point_rings: List[Circle] = []     # rings around selected points
        self.grid_step = 0.0                     # spacing of the drawn lines

    # -- per frame ------------------------------------------------------------------
    def sync(self, ed: Editor) -> None:
        doc = ed.doc
        key = (doc.version, tuple(ed.selection), canvas.zoom, doc.base_dir(), doc.size)
        if key != self._seen:
            self._seen = key
            self._sync_frame(doc.size)
            self._sync_items(ed)
        self._sync_grid(ed)
        self._sync_overlay(ed)

    def _sync_frame(self, size) -> None:
        w, h = size
        self.frame.center = (w / 2, h / 2)
        self.frame.width = w
        self.frame.height = h
        self.frame.line_width = 1.5 / canvas.zoom

    # -- items ---------------------------------------------------------------------
    def _sync_items(self, ed: Editor) -> None:
        doc = ed.doc
        selected = set(ed.selection)
        live = set()
        for item in doc.items:
            iid = item["id"]
            live.add(iid)
            key = _shape_key(item, doc)
            iv = self.items.get(iid)
            if iv is None or iv.key != key:
                if iv is not None:
                    iv.shape.destroy()
                iv = self.items[iid] = _ItemView(_make_shape(item, doc), key, None)
            if iv.item != item:
                _apply(iv.shape, item)
                iv.item = dict(item)
            _style(iv.shape, item, iid in selected)
        for iid in [i for i in self.items if i not in live]:
            self.items.pop(iid).shape.destroy()
        order = [item["id"] for item in doc.items]
        if order != self._order:
            for iid in order:
                self.items[iid].shape.move_to_front()
            self._order = order

    # -- grid -----------------------------------------------------------------------
    def _sync_grid(self, ed: Editor) -> None:
        gv = canvas.game_view
        view = (gv.left, gv.bottom, gv.right, gv.top)
        key = (view, canvas.zoom, ed.grid, ed.snap, ed.doc.size)
        if key == self._grid_key:
            return
        self._grid_key = key
        lines = []
        self.grid_step = 0.0
        if ed.snap and ed.grid > 0:
            step = ed.grid
            while step * canvas.zoom < GRID_MIN_PX:
                step *= 5 if str(int(step))[0] in "12" else 2
            self.grid_step = step
            w, h = ed.doc.size
            x0, y0 = max(view[0], 0.0), max(view[1], 0.0)
            x1, y1 = min(view[2], w), min(view[3], h)
            if x1 > x0 and y1 > y0:
                gx = math.ceil(x0 / step) * step
                while gx <= x1 and len(lines) < MAX_GRID_LINES:
                    lines.append(((gx, y0), (gx, y1)))
                    gx += step
                gy = math.ceil(y0 / step) * step
                while gy <= y1 and len(lines) < MAX_GRID_LINES:
                    lines.append(((x0, gy), (x1, gy)))
                    gy += step
        while len(self._grid_lines) < len(lines):
            ln = Line(p1=(0, 0), p2=(1, 0), layer=BG_LAYER)
            ln.line = Color(1, 1, 1, 0.07)
            self._grid_lines.append(ln)
        for i, ln in enumerate(self._grid_lines):
            if i < len(lines):
                ln.p1, ln.p2 = lines[i]
                ln.line_width = 1.0 / canvas.zoom
                ln.visible = True
            else:
                ln.visible = False

    # -- overlay ----------------------------------------------------------------------
    def _sync_overlay(self, ed: Editor) -> None:
        size = HANDLE_PX / canvas.zoom
        handles = ed.handles()
        knob = [h for h in handles if h.role in ("rotate", "group_rotate")]
        resize = [h for h in handles if h not in knob]
        while len(self._handles) < len(resize):
            r = Rect(center=(0, 0), width=1, height=1, layer=OVERLAY_LAYER)
            r.fill = "white"
            r.line = "black"
            self._handles.append(r)
        angle = ed.handles_angle()
        for i, r in enumerate(self._handles):
            if i < len(resize):
                h = resize[i]
                r.center = (h.x, h.y)
                r.width = r.height = size
                r.angle = angle if h.role in ("resize", "group_resize") else 0.0
                r.line_width = 1.0 / canvas.zoom
                r.visible = True
            else:
                r.visible = False
        if knob:
            self._rotate_knob.center = (knob[0].x, knob[0].y)
            self._rotate_knob.radius = size * 0.6
            self._rotate_knob.line_width = 1.0 / canvas.zoom
        self._rotate_knob.visible = bool(knob)
        box_frame = ed.group_frame() if handles else None
        if box_frame is not None:
            cx, cy, w, h, r = box_frame
            self._group_frame.center = (cx, cy)
            self._group_frame.width = max(w, 1e-3)
            self._group_frame.height = max(h, 1e-3)
            self._group_frame.angle = r
            self._group_frame.line_width = 1.0 / canvas.zoom
        self._group_frame.visible = box_frame is not None
        if ed.band is not None:
            x0, y0, x1, y1 = ed.band
            self._band.center = ((x0 + x1) / 2, (y0 + y1) / 2)
            self._band.width = max(x1 - x0, 1e-3)
            self._band.height = max(y1 - y0, 1e-3)
            self._band.line_width = 1.0 / canvas.zoom
        self._band.visible = ed.band is not None
        images = [it for it in ed.selected_items() if it["kind"] == "image"]
        while len(self._image_marks) < len(images):
            r = Rect(center=(0, 0), width=1, height=1, layer=OVERLAY_LAYER)
            r.fill = None
            r.line = SELECTED
            self._image_marks.append(r)
        for i, r in enumerate(self._image_marks):
            if i < len(images):
                it = images[i]
                r.center = it["center"]
                r.width, r.height = it["width"], it["height"]
                r.angle = it["angle"]
                r.line_width = 2.0 / canvas.zoom
                r.visible = True
            else:
                r.visible = False
        points = [it for it in ed.selected_items() if it["kind"] == "point"]
        while len(self._point_rings) < len(points):
            ring = Circle(center=(0, 0), radius=1, layer=OVERLAY_LAYER)
            ring.fill = None
            ring.line = SELECTED
            self._point_rings.append(ring)
        for i, ring in enumerate(self._point_rings):
            if i < len(points):
                ring.center = points[i]["center"]
                ring.radius = POINT_RING_PX / canvas.zoom
                ring.line_width = 2.0 / canvas.zoom
                ring.visible = True
            else:
                ring.visible = False
        pts = list(ed.pending)
        if pts and ed.hover is not None:
            pts.append(ed.hover)
        segs = list(zip(pts, pts[1:]))
        while len(self._pending) < len(segs):
            ln = Line(p1=(0, 0), p2=(1, 0), layer=OVERLAY_LAYER)
            ln.line = SELECTED
            self._pending.append(ln)
        for i, ln in enumerate(self._pending):
            if i < len(segs) and segs[i][0] != segs[i][1]:
                ln.p1, ln.p2 = segs[i]
                ln.line_width = 1.5 / canvas.zoom
                ln.visible = True
            else:
                ln.visible = False


# -- one item ---------------------------------------------------------------------------

def _shape_key(item: Dict[str, Any], doc) -> tuple:
    """What forces a new Graphic (kind, point list, image file)."""
    kind = item["kind"]
    if kind in ("polygon", "track"):
        return (kind, item["points"], item.get("closed", False), item.get("smooth", 0.0))
    if kind == "image":
        return (kind, doc.image_path(item))
    if kind == "regular_polygon":
        return (kind, item["n"])              # n is fixed at construction
    return (kind,)


def _make_shape(item: Dict[str, Any], doc):
    kind = item["kind"]
    if kind == "rect":
        return Rect(center=(0, 0), width=1, height=1, layer=ITEM_LAYER)
    if kind == "ellipse":
        return Ellipse(center=(0, 0), width=1, height=1, layer=ITEM_LAYER)
    if kind in ("circle", "point"):
        return Circle(center=(0, 0), radius=1, layer=ITEM_LAYER)
    if kind == "line":
        return Line(p1=(0, 0), p2=(1, 0), layer=ITEM_LAYER)
    if kind == "polygon":
        return Polygon(points=list(item["points"]), layer=ITEM_LAYER)
    if kind == "regular_polygon":
        return RegularPolygon(n=item["n"], center=(0, 0), radius=1, layer=ITEM_LAYER)
    if kind == "track":
        return Track(points=list(item["points"]), smooth=item["smooth"], closed=item["closed"],
                     color=UNGROUPED, layer=ITEM_LAYER)
    if kind == "image":
        return Sprite(doc.image_path(item), center=(0, 0), width=1, height=1, layer=ITEM_LAYER)
    raise AssertionError(kind)


def _apply(shape, item: Dict[str, Any]) -> None:
    kind = item["kind"]
    if kind in ("rect", "ellipse", "image"):
        shape.center = item["center"]
        shape.width = item["width"]
        shape.height = item["height"]
        shape.angle = item["angle"]
        if kind == "image":
            shape.alpha = 0.5 if item["guide"] else 1.0
    elif kind == "circle":
        shape.center = item["center"]
        shape.radius = item["radius"]
    elif kind == "regular_polygon":
        shape.center = item["center"]
        shape.radius = item["radius"]
        shape.angle = item["angle"]
    elif kind == "point":
        shape.center = item["center"]
    elif kind == "line":
        shape.p1 = item["p1"]
        shape.p2 = item["p2"]


def _style(shape, item: Dict[str, Any], selected: bool) -> None:
    kind = item["kind"]
    color = Color(SELECTED) if selected else group_color(item["groups"])
    width = (2.5 if selected else 1.5) / canvas.zoom
    if kind == "image":
        return                                   # images draw as themselves
    if kind == "point":
        shape.radius = 5.0 / canvas.zoom
        shape.fill = color
        shape.line = "black"
        shape.line_width = 1.0 / canvas.zoom
        return
    shape.line = color
    shape.line_width = width
    if kind in ("rect", "ellipse", "circle", "polygon", "regular_polygon"):
        shape.fill = translucent(color, 0.22)
