"""The editor controller: tools, selection, gestures, commands. No Graphics.

``Editor`` turns pointer / key events (world coordinates, y up) into document
edits and undo steps. The camera is a ``Viewport`` (``zoom``, ``pan_by``,
``zoom_about``, ``fit``, ``actual_size``) supplied by the host — Scena in the app,
a fake in tests. The host draws what ``Editor`` exposes (``selection``,
``band``, ``pending``, ``handles()``) and asks ``cursor()`` for the pointer.

Gesture rules (Editor Design.md — Editor):

- Select tool: click selects; Shift+click adds / removes; drag a shape moves
  the selection (Alt / Option+drag moves copies); drag a handle resizes /
  rotates; drag empty canvas is the selection box (Shift adds); a click (no
  drag) on the already-selected shape cycles to the shape under it. Panning:
  Hand tool, Space+drag, middle button.
- Several selected: a frame around the items that move, corner handles that
  scale them evenly about the opposite corner, a knob that turns them about
  the frame's center.
- Shape tools: drag draws; a click makes a ``DEFAULT_SIZE`` shape (rect /
  ellipse / concave: top-left at the click; circle, regular polygon: centered; line:
  rightwards). A regular polygon is drawn from the center out: a hexagon
  (``SIDES``) with a vertex on top; Sides is a panel field. A concave is drawn
  like a rect (scooped at its top left); Scoop and Rim are panel fields.
- Shift while dragging turns snapping off. Snapping puts the corner you hold
  on the grid: the dragged corner when drawing or resizing; when moving, the
  corner of the selection's box nearest the press. Rotation snaps to 15°.
- One undo step per finished gesture; pan, zoom and selection are not steps.
"""
from __future__ import annotations

import math
import re
import sys
from typing import Any, Dict, List, Optional, Protocol, Tuple

from scena.level_format import code_for
from scena.validate import did_you_mean

from . import geometry as geo
from .doc import LevelDoc, NameTaken
from .i18n import t
from .undo import History

TOOLS = ("select", "hand", "rect", "ellipse", "circle", "line", "polygon", "triangle",
         "regular_polygon", "track", "concave", "point",
         "image")
TOOL_KEYS = {"V": "select", "H": "hand", "R": "rect", "E": "ellipse", "U": "concave",
             "C": "circle", "L": "line", "D": "triangle",
             "G": "polygon", "N": "regular_polygon", "A": "track", "P": "point",
             "I": "image"}
KEY_OF = {tool: key for key, tool in TOOL_KEYS.items()}
PRIMARY = "CMD" if sys.platform == "darwin" else "CTRL"
REDO = "CMD+SHIFT+Z" if sys.platform == "darwin" else "CTRL+Y"   # Ctrl+Shift+Z quits Scena
ALT_LABEL = "Option" if sys.platform == "darwin" else "Alt"      # Alt+drag copies
# Holding Primary in Pan or a drawing tool makes a press a Select press.
SPRING_TOOLS = ("hand", "rect", "ellipse", "concave", "circle", "line", "polygon",
                "triangle", "regular_polygon", "track", "point")
SIDES = 6            # a new regular polygon: a hexagon…
HEADING = 90.0       # …with a vertex on top (a triangle / pentagon points up)


def _rim_text(value: Any) -> Tuple[float, float]:
    """The panel's Rim field: ``"20"`` (both axes) or ``"20, 0"`` (x, y)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (float(value), float(value))
    parts = [p for p in re.split(r"[,;\s]+", str(value).strip()) if p]
    if len(parts) == 1:
        parts = parts * 2
    if len(parts) != 2:
        raise ValueError(t("error.rim", value=str(value)))
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        raise ValueError(t("error.rim", value=str(value))) from None


def rim_text(rim: Tuple[float, float]) -> str:
    """A rim as the panel shows it: ``"20"`` when both axes agree, else ``"20, 0"``."""
    mx, my = (f"{v:g}" for v in rim)
    return mx if mx == my else f"{mx}, {my}"


def key_label(combo: str) -> str:
    """``"CMD+SHIFT+Z"`` → ``"Cmd+Shift+Z"`` (a shortcut as the UI shows it)."""
    return "+".join(k.capitalize() if len(k) > 1 else k for k in combo.split("+"))
DEFAULT_SIZE = 100.0  # a click with a shape tool (every grid step divides it)
DRAG_PX = 3.0       # press → drag threshold, screen pixels
HANDLE_PX = 9.0     # handle size on screen
PICK_PX = 5.0       # extra reach for thin shapes (lines, points, paths)
ROTATE_PX = 28.0    # rotate knob above the top edge
GRID_SIZES = (1, 5, 10, 20, 50)
LEFT, RIGHT, MIDDLE = 0, 1, 2


class Viewport(Protocol):
    zoom: float

    def pan_by(self, dx: float, dy: float) -> None: ...      # moves the CONTENT
    def zoom_about(self, factor: float, x: float, y: float) -> None: ...
    def fit(self, box: Tuple[float, float, float, float]) -> None: ...
    def actual_size(self) -> None: ...


class Editor:
    def __init__(self, doc: Optional[LevelDoc] = None, viewport: Optional[Viewport] = None,
                 *, grid: float = 10.0):
        self.doc = doc if doc is not None else LevelDoc()
        self.history = History(self.doc)
        self.viewport = viewport
        self.grid = float(grid)
        self.snap = True
        self.tool = "select"
        self.selection: List[int] = []
        self.gesture: Optional[Dict[str, Any]] = None
        self.pending: List[geo.Pt] = []          # polygon / track points so far
        self.hover: Optional[geo.Pt] = None       # pointer, for previews
        self.band: Optional[Tuple[float, float, float, float]] = None
        self.message: Optional[str] = None        # status-bar note for the host
        self.clipboard: List[Dict[str, Any]] = []  # copied items (kept across New / Open)
        self._pastes = 0
        self.image_requested = False              # host opens the image dialog
        # Primary held (the host sets it): in Pan or a drawing tool a press
        # acts as Select — decided at the press, so a gesture never switches.
        self.select_held = False
        self.picked_group: Optional[str] = None   # selected_group's tie-breaker
        self._handles_key: Any = None
        self._handles: List[geo.Handle] = []
        self._frame: Optional[Tuple[float, float, float, float, float]] = None

    # -- document -------------------------------------------------------------
    def set_doc(self, doc: LevelDoc) -> None:
        """Edit another document (New / Open). Undo history starts over."""
        self.cancel()
        self.doc = doc
        self.history.reset(doc)
        self.selection = []

    # -- helpers ----------------------------------------------------------------
    @property
    def zoom(self) -> float:
        return self.viewport.zoom if self.viewport is not None else 1.0

    def _px(self, pixels: float) -> float:
        return pixels / self.zoom

    def _grid(self, shift: bool) -> float:
        return 0.0 if (shift or not self.snap) else self.grid

    def selected_items(self) -> List[Dict[str, Any]]:
        return [self.doc.get(i) for i in self.selection if self.doc.has(i)]

    def single(self) -> Optional[Dict[str, Any]]:
        items = self.selected_items()
        return items[0] if len(items) == 1 else None

    def items_at(self, x: float, y: float) -> List[Dict[str, Any]]:
        """Items under ``(x, y)``, topmost first."""
        tol = self._px(PICK_PX)
        return [it for it in reversed(self.doc.items) if geo.contains(it, x, y, tol)]

    def handles(self) -> List[geo.Handle]:
        """Handles of the selection: one unlocked item's own; for several, the
        group's corners and rotate knob (around the items that move); else none.
        Cached: the view and the cursor ask every frame."""
        key = (id(self.doc), self.doc.version, tuple(self.selection), self.zoom,
               self.gesture.get("delta") if self.gesture else None)
        if self._handles_key == key:
            return self._handles
        box_frame = self._group_frame_now()
        self._frame = box_frame
        if box_frame is not None:
            out = geo.group_handles(box_frame, self._px(ROTATE_PX))
        else:
            item = self.single()
            out = [] if item is None or item["locked"] else geo.handles(item, self._px(ROTATE_PX))
        self._handles_key, self._handles = key, out
        return out

    def _movable(self) -> List[Dict[str, Any]]:
        return [it for it in self.selected_items() if not it["locked"]]

    def group_frame(self) -> Optional[Tuple[float, float, float, float, float]]:
        """``(cx, cy, w, h, angle)`` of a group selection's handles: the box of
        the items that move (two or more selected), turned while a group
        rotation runs. None for one item, or when the box is a single point."""
        self.handles()                 # computes it with the handles (cached)
        return self._frame

    def _group_frame_now(self) -> Optional[Tuple[float, float, float, float, float]]:
        g = self.gesture
        if g is not None and g["kind"] == "group_rotate":
            (cx, cy), (w, h) = g["origin"], g["size"]
            return cx, cy, w, h, g["delta"]
        if len(self.selection) < 2:
            return None
        box = geo.union_aabb(self._movable())
        if box is None or (box[2] - box[0] <= 0 and box[3] - box[1] <= 0):
            return None
        return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2,
                box[2] - box[0], box[3] - box[1], 0.0)

    def handles_angle(self) -> float:
        """How far the handle squares turn: the group frame's, else the item's."""
        box_frame = self.group_frame()
        if box_frame is not None:
            return box_frame[4]
        item = self.single()
        return item.get("angle", 0.0) if item is not None else 0.0

    def handle_at(self, x: float, y: float) -> Optional[geo.Handle]:
        """The handle under the pointer. On a small shape the handles cover its
        middle: a handle wins only when the pointer is nearer to it than to
        the shape's center, so the shape stays clickable (select, cycle, move)."""
        tol = self._px(HANDLE_PX) * 0.9
        best = None
        for h in self.handles():
            d = math.dist((x, y), (h.x, h.y))
            if d <= tol and (best is None or d < best[0]):
                best = (d, h)
        if best is None:
            return None
        d, h = best
        if h.role in ("resize", "radius", "group_resize"):
            box_frame = self.group_frame()
            center = box_frame[:2] if box_frame is not None else _center(self.single())
            if math.dist((x, y), center) < d:
                return None
        return h

    def _filter_selection(self) -> None:
        self.selection = [i for i in self.selection if self.doc.has(i)]

    # -- tools ------------------------------------------------------------------
    def set_tool(self, tool: str) -> None:
        if tool not in TOOLS:
            raise ValueError(f"unknown tool {tool!r}")
        self.cancel()
        self.tool = tool
        if tool == "select":
            self.selection = []       # choosing Select starts a fresh selection
        if tool == "image":
            self.image_requested = True

    @property
    def select_standby(self) -> bool:
        """Primary is held in Pan / a drawing tool and no gesture runs: the
        next press is a Select press (cursor, hint and the Select button say so)."""
        return self.select_held and self.tool in SPRING_TOOLS and self.gesture is None

    def hint(self) -> str:
        if self.gesture is not None and self.gesture["kind"] == "move":
            tool = "move"                 # what the keys do while dragging
        else:
            tool = "select" if self.select_standby else self.tool
        return t(f"hint.{tool}", primary=key_label(PRIMARY), alt=ALT_LABEL)

    # -- pointer -----------------------------------------------------------------
    def pointer_down(self, x: float, y: float, button: int = LEFT, *,
                     shift: bool = False, space: bool = False, alt: bool = False) -> None:
        self.hover = (x, y)
        spring = self.select_held and self.tool in SPRING_TOOLS
        if button == MIDDLE or space or (button == LEFT and self.tool == "hand" and not spring):
            self.gesture = {"kind": "pan", "grab": (x, y)}
            return
        if button != LEFT:
            return
        if self.tool == "select" or spring:
            # Polygon / path points drawn so far stay: a Select press between
            # clicks neither adds a point nor drops them.
            self._select_down(x, y, shift, alt)
        elif self.tool in ("rect", "ellipse", "concave", "circle", "line", "regular_polygon",
                           "triangle"):
            start = geo.snap_point((x, y), self._grid(shift))
            self.gesture = {"kind": "create", "start": start, "id": None, "press": (x, y)}
        elif self.tool in ("polygon", "track"):
            p = geo.snap_point((x, y), self._grid(shift))
            if not self.pending or self.pending[-1] != p:
                self.pending.append(p)
        elif self.tool == "point":
            self.gesture = {"kind": "place"}

    def _select_down(self, x: float, y: float, shift: bool, alt: bool = False) -> None:
        h = self.handle_at(x, y)
        if h is not None and h.role.startswith("group_"):
            movable = self._movable()
            box = geo.union_aabb(movable)
            orig = [dict(it) for it in movable]
            if h.role == "group_resize":
                self.gesture = {"kind": "group_scale", "signs": h.key, "box": box, "orig": orig}
            else:
                origin = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
                self.gesture = {"kind": "group_rotate", "origin": origin,
                                "size": (box[2] - box[0], box[3] - box[1]),
                                "a0": geo.angle_toward(origin, (x, y)), "delta": 0.0,
                                "orig": orig}
            return
        if h is not None:
            item = self.single()
            g = {"kind": h.role, "key": h.key, "id": item["id"], "orig": dict(item)}
            if h.role == "resize":
                g["anchor"] = geo.anchor_for(item, h.key)
            self.gesture = g
            return
        hits = self.items_at(x, y)
        if not hits:
            # Empty canvas: a selection box (Shift keeps what is selected).
            # Panning is the Hand tool, Space+drag or the middle button.
            if not shift:
                self.selection = []
            self.gesture = {"kind": "band", "start": (x, y), "base": list(self.selection)}
            self.band = (x, y, x, y)
            return
        top = hits[0]
        cycle_to = None
        toggle_off = None
        if shift:
            # Shift+press adds; Shift+click (no drag) on a selected shape removes
            # it on release — so Shift+drag of a selected shape still moves it
            # (Shift turns snapping off).
            if top["id"] in self.selection:
                toggle_off = top["id"]
            else:
                self.selection.append(top["id"])
        elif top["id"] in self.selection:
            if self.selection == [top["id"]] and len(hits) > 1:
                cycle_to = hits[1]["id"]
        else:
            self.selection = [top["id"]]
        self.gesture = {"kind": "press", "start": (x, y), "cycle_to": cycle_to,
                        "toggle_off": toggle_off, "alt": alt}

    def pointer_move(self, x: float, y: float, *, shift: bool = False,
                     straight: bool = False) -> None:
        """Pointer motion (call once per event — not from both move and drag).

        ``straight`` (Primary held, read every event so it can start or stop
        mid-drag): a move keeps to the axis the pointer has gone furthest
        along; the other axis stays exactly where it was (Inkscape's Ctrl)."""
        self.hover = (x, y)
        g = self.gesture
        if g is None:
            return
        kind = g["kind"]
        grid = self._grid(shift)
        if kind == "pan":
            if self.viewport is not None:
                # pan_by moves the content: bring the grabbed point back under
                # the pointer (x, y are fresh world coordinates each event).
                self.viewport.pan_by(x - g["grab"][0], y - g["grab"][1])
            return
        if kind == "press":
            if math.dist((x, y), g["start"]) < self._px(DRAG_PX):
                return
            movable = [it for it in self.selected_items() if not it["locked"]]
            if not movable:
                self.gesture = None
                return
            if g["alt"]:
                # Alt / Option+drag: copies, made where the originals are, move;
                # the originals stay. Copy and move are one undo step.
                self.selection = self.doc.duplicate([it["id"] for it in movable], (0.0, 0.0))
                movable = self.selected_items()
            box = geo.union_aabb(movable)
            ref = geo.nearest_corner(box, g["start"])
            self.gesture = g = {"kind": "move", "start": g["start"], "ref": ref,
                                "orig": [dict(it) for it in movable]}
            kind = "move"
        if kind == "move":
            dx, dy = x - g["start"][0], y - g["start"][1]
            along_x = abs(dx) >= abs(dy)
            if grid:
                dx, dy = geo.snapped_delta(g["ref"], dx, dy, grid)
            if straight:
                # After the snap: the held axis stays put even off the grid,
                # so a copy lines up with its original.
                dx, dy = (dx, 0.0) if along_x else (0.0, dy)
            for orig in g["orig"]:
                self.doc.update(orig["id"], **geo.translate(orig, dx, dy))
        elif kind == "band":
            x0, y0 = g["start"]
            self.band = (min(x0, x), min(y0, y), max(x0, x), max(y0, y))
            inside = [it["id"] for it in self.doc.items if geo.inside(it, self.band)]
            self.selection = g["base"] + [i for i in inside if i not in g["base"]]
        elif kind == "create":
            self._create_move(g, x, y, grid)
        elif kind == "resize":
            p = geo.snap_point((x, y), grid)
            orig = g["orig"]
            fields = geo.resize(orig, g["key"], g["anchor"], p,
                                keep_aspect=orig["kind"] == "image")
            self.doc.update(g["id"], **fields)
        elif kind == "rotate":
            angle = geo.heading_toward(g["orig"], (x, y))
            self.doc.update(g["id"], angle=geo.snap_angle(angle) if grid else angle)
        elif kind == "group_scale":
            factor, anchor = geo.group_scale(g["box"], g["signs"], (x, y), grid)
            for orig in g["orig"]:
                self.doc.update(orig["id"], **geo.scale_item(orig, anchor, factor))
        elif kind == "group_rotate":
            delta = geo.angle_toward(g["origin"], (x, y)) - g["a0"]
            delta = geo.snap_angle(delta) if grid else delta % 360.0
            g["delta"] = delta
            for orig in g["orig"]:
                self.doc.update(orig["id"], **geo.rotate_item(orig, g["origin"], delta))
        elif kind == "radius":
            r = math.dist(g["orig"]["center"], (x, y))
            self.doc.update(g["id"], radius=max(geo.snap(r, grid), 0.0))
        elif kind == "end":
            self.doc.update(g["id"], **{g["key"]: geo.snap_point((x, y), grid)})
        elif kind == "vertex":
            pts = list(g["orig"]["points"])
            pts[g["key"]] = geo.snap_point((x, y), grid)
            self.doc.update(g["id"], points=tuple(pts))

    def _create_move(self, g: Dict[str, Any], x: float, y: float, grid: float) -> None:
        if g["id"] is None and math.dist((x, y), g["press"]) < self._px(DRAG_PX):
            return
        sx, sy = g["start"]
        ex, ey = geo.snap_point((x, y), grid)
        tool = self.tool
        if tool in ("rect", "ellipse", "concave"):
            fields = {"center": ((sx + ex) / 2, (sy + ey) / 2),
                      "width": abs(ex - sx), "height": abs(ey - sy)}
        elif tool == "regular_polygon":
            fields = {"center": (sx, sy), "radius": geo.snap(math.dist((sx, sy), (x, y)), grid),
                      "n": SIDES, "angle": HEADING}
        elif tool == "triangle":
            fields = {"center": (sx, sy), "radius": geo.snap(math.dist((sx, sy), (x, y)), grid),
                      "angle": HEADING}
        elif tool == "circle":
            fields = {"center": (sx, sy), "radius": geo.snap(math.dist((sx, sy), (x, y)), grid)}
        else:
            fields = {"p1": (sx, sy), "p2": (ex, ey)}
        if g["id"] is None:
            g["id"] = self.doc.add({"kind": tool, **fields})
        else:
            self.doc.update(g["id"], **fields)

    def pointer_up(self, x: float, y: float, button: int = LEFT, *,
                   shift: bool = False) -> None:
        self.hover = (x, y)
        g, self.gesture = self.gesture, None
        self.band = None
        if g is None:
            return
        kind = g["kind"]
        if kind == "press":
            if g.get("toggle_off") is not None:
                self.selection.remove(g["toggle_off"])
            elif g.get("cycle_to") is not None:
                self.selection = [g["cycle_to"]]
            return
        if kind in ("move", "resize", "rotate", "radius", "end", "vertex", "group_scale",
                    "group_rotate"):
            self.history.commit()
            return
        if kind == "create":
            item_id = g["id"]
            if item_id is None:                      # a click: a default shape
                self._created(self.doc.add(self._default_shape(g["start"])))
                return
            item = self.doc.get(item_id)
            if self._degenerate(item):
                self.history.discard()
                return
            self._created(item_id)
            return
        if kind == "place":
            p = geo.snap_point((x, y), self._grid(shift))
            self._created(self.doc.add({"kind": "point", "center": p}))

    def _default_shape(self, at: Tuple[float, float]) -> Dict[str, Any]:
        """The item a click (no drag) makes: ``DEFAULT_SIZE`` wide, top-left at
        ``at`` (circle, regular polygon, triangle: centered there; line: from
        there to the right)."""
        x, y = at
        s = DEFAULT_SIZE
        if self.tool == "regular_polygon":
            return {"kind": "regular_polygon", "center": (x, y), "radius": s / 2, "n": SIDES,
                    "angle": HEADING}
        if self.tool == "triangle":
            return {"kind": "triangle", "center": (x, y), "radius": s / 2, "angle": HEADING}
        if self.tool == "circle":
            return {"kind": "circle", "center": (x, y), "radius": s / 2}
        if self.tool == "line":
            return {"kind": "line", "p1": (x, y), "p2": (x + s, y)}
        return {"kind": self.tool, "center": (x + s / 2, y - s / 2), "width": s, "height": s}

    def _degenerate(self, item: Dict[str, Any]) -> bool:
        a, b, c, d = geo.aabb(item)
        if item["kind"] in ("circle", "regular_polygon", "triangle"):
            return item["radius"] <= 0
        if item["kind"] == "line":
            return item["p1"] == item["p2"]
        return (c - a) <= 0 or (d - b) <= 0

    def _created(self, item_id: int) -> None:
        self.history.commit()
        self.selection = [item_id]
        self.tool = "select"

    def double_click(self, x: float, y: float) -> None:
        if self.tool in ("polygon", "track") and not self.select_held:
            self.finish_points()

    def finish_points(self) -> bool:
        """Close the polygon / end the path being drawn. False if too few points."""
        pts = []
        for p in self.pending:
            if not pts or pts[-1] != p:
                pts.append(p)
        need = 3 if self.tool == "polygon" else 2
        self.pending = []
        if len(pts) < need:
            return False
        self._created(self.doc.add({"kind": self.tool, "points": pts}))
        return True

    # -- keys ------------------------------------------------------------------------
    def key(self, name: str, *, shift: bool = False) -> bool:
        """A key with no Cmd / Ctrl. True when the editor used it."""
        if name in TOOL_KEYS and self.gesture is None:
            self.set_tool(TOOL_KEYS[name])
            return True
        if name == "ENTER" and self.tool in ("polygon", "track"):
            self.finish_points()
            return True
        if name == "ESC":
            if self.gesture is not None or self.pending:
                self.cancel()
            elif self.tool != "select":
                self.tool = "select"
            else:
                self.selection = []
            return True
        if name in ("DEL", "BACKSPACE"):
            self.delete()
            return True
        if name in ("LEFT", "RIGHT", "UP", "DOWN"):
            step = self.grid if shift else 1.0
            dx = {"LEFT": -step, "RIGHT": step}.get(name, 0.0)
            dy = {"DOWN": -step, "UP": step}.get(name, 0.0)
            self.nudge(dx, dy)
            return True
        return False

    def cancel(self) -> None:
        """Drop the gesture in progress (and its uncommitted edits)."""
        g = self.gesture
        self.gesture = None
        self.band = None
        self.pending = []
        if g is not None:
            if g["kind"] == "band":
                self.selection = g["base"]
            self.history.discard()
            self._filter_selection()

    # -- commands ------------------------------------------------------------------------
    def undo(self) -> bool:
        self.cancel()
        done = self.history.undo()
        self._filter_selection()
        return done

    def redo(self) -> bool:
        self.cancel()
        done = self.history.redo()
        self._filter_selection()
        return done

    def delete(self) -> None:
        ids = [it["id"] for it in self.selected_items() if not it["locked"]]
        if ids:
            self.doc.remove(ids)
            self.history.commit()
            self._filter_selection()

    def duplicate(self) -> None:
        step = self.grid or 10.0
        new = self.doc.duplicate(self.selection, (step, -step))
        if new:
            self.history.commit()
            self.selection = new

    def restack(self, *, front: bool) -> None:
        self.doc.restack(self.selection, front=front)
        self.history.commit()

    def pack(self, axis: str) -> bool:
        """Row (``"x"``) / Column (``"y"``): the selected items that move, edge to
        edge with no gaps, from the leftmost / bottom one (``geometry.pack``).
        One undo step; none when nothing moved."""
        movable = self._movable()
        if len(movable) < 2:
            return False
        shifts = geo.pack(movable, axis)
        for it in movable:
            dx, dy = shifts[it["id"]]
            if dx or dy:
                self.doc.update(it["id"], **geo.translate(it, dx, dy))
        if not self.history.commit():
            return False
        self.message = t("note.row" if axis == "x" else "note.column", count=len(movable))
        return True

    def select_group(self, name: Optional[str]) -> None:
        """Select every item in group ``name``, in file order; ``None`` selects
        nothing (not an undo step). The name is kept as :meth:`selected_group`'s
        tie-breaker."""
        self.picked_group = name
        self.selection = ([] if name is None else
                          [it["id"] for it in self.doc.items if name in it["groups"]])

    def selected_group(self) -> Optional[str]:
        """The group whose items are exactly the selection, else None — computed
        from the selection, never remembered: a Shift+click more and it is None.
        Two groups with the same items: the one last picked with
        :meth:`select_group` when it is one of them (you chose "xyz", it says
        "xyz", not "abc"), else the first A–Z."""
        chosen = set(self.selection)
        if not chosen:
            return None
        members: Dict[str, set] = {}
        for it in self.doc.items:
            for g in it["groups"]:
                members.setdefault(g, set()).add(it["id"])
        exact = [g for g, ids in members.items() if ids == chosen]
        if self.picked_group in exact:
            return self.picked_group
        return min(exact, key=lambda g: (g.casefold(), g)) if exact else None

    def nudge(self, dx: float, dy: float) -> None:
        for it in self.selected_items():
            if not it["locked"]:
                self.doc.update(it["id"], **geo.translate(it, dx, dy))
        self.history.commit()

    def select_all(self) -> None:
        self.selection = [it["id"] for it in self.doc.items]

    def copy_code(self) -> str:
        """Copy-as-code text for the selection (one block per item)."""
        return "\n".join(code_for({k: v for k, v in it.items() if k != "id"})
                         for it in self.selected_items())

    def copy(self) -> str:
        """Copy the selected items inside the editor (for :meth:`paste`, also
        into another level) and return their Copy-as-code text."""
        items = []
        for it in self.selected_items():
            item = {k: v for k, v in it.items() if k != "id"}
            if item["kind"] == "image":
                item["file"] = self.doc.image_path(it)        # absolute: survives Open
            items.append(item)
        if items:
            self.clipboard = items
            self._pastes = 0
        return self.copy_code()

    def cut(self) -> str:
        text = self.copy()
        self.delete()
        return text

    def paste(self) -> List[int]:
        """Paste the copied items, one grid step further each time. Names are
        made unique; image files are re-pointed from this level's folder."""
        if not self.clipboard:
            return []
        self.cancel()
        self._pastes += 1
        step = (self.grid or 10.0) * self._pastes
        new = []
        for item in self.clipboard:
            item = dict(item)
            item.update(geo.translate(item, step, -step))
            if item.get("name"):
                taken = self.doc.names()
                if item["name"] in taken:
                    item["name"] = self.doc.free_name(item["name"])
            if item["kind"] == "image" and self.doc.path:
                item["file"] = self.doc.relative_file(item["file"])
            new.append(self.doc.add(item))
        self.history.commit()
        self.selection = new
        return new

    def add_image(self, path: str, pixel_size: Tuple[float, float],
                  center: Tuple[float, float]) -> int:
        """Place an image at its pixel size (1 pixel = 1 design unit)."""
        self.image_requested = False
        self.tool = "select"
        w, h = pixel_size
        item_id = self.doc.add({"kind": "image", "file": path, "center": center,
                                "width": w, "height": h})
        self._created(item_id)
        return item_id

    # -- panel edits ---------------------------------------------------------------------
    def set_field(self, field: str, value: Any, item_id: Optional[int] = None, *,
                  record: bool = True) -> bool:
        """Change one field of an item (panel). One undo step.

        ``item_id`` defaults to the single selected item. The panel passes the
        item the field was showing: clicking the canvas commits a typed value
        in the same event that changes the selection. ``x`` / ``y`` move the
        item's center (any kind); ``groups`` takes comma-separated text.
        Errors go to ``message``; returns False. ``record=False`` leaves the
        step open (a slider drag: the panel calls ``history.commit()`` when
        the handle is let go).
        """
        if item_id is not None:
            item = self.doc.get(item_id) if self.doc.has(item_id) else None
        else:
            item = self.single()
        if item is None:
            return False
        try:
            if field in ("x1", "y1", "x2", "y2"):
                end = "p" + field[1]
                px, py = item[end]
                point = (float(value), py) if field[0] == "x" else (px, float(value))
                self.doc.update(item["id"], **{end: point})
            elif field in ("x", "y"):
                cx, cy = _center(item)
                dx = float(value) - cx if field == "x" else 0.0
                dy = float(value) - cy if field == "y" else 0.0
                self.doc.update(item["id"], **geo.translate(item, dx, dy))
            elif field == "groups":
                return self.set_groups(value, [item["id"]])
            elif field == "rim":
                self.doc.update(item["id"], rim=_rim_text(value))
            else:
                self.doc.update(item["id"], **{field: value})
        except NameTaken as e:
            self.message = t("error.name_taken", name=str(e))
            return False
        except (TypeError, ValueError) as e:
            self.message = str(e)
            return False
        if record:
            self.history.commit()
        return True

    def set_groups(self, value: Any, ids: Optional[List[int]] = None) -> bool:
        """The panel's Groups field (comma-separated text) for one or many items.

        One item: its groups become exactly the typed list. Several: the field
        showed the groups **every** item has; a name typed there is added to
        all of them, a name deleted from it is removed from all of them, and
        groups only some items have stay as they are. One undo step (none when
        nothing changed). ``message`` says what happened, and a name new to
        the level that is close to an existing group gets a did-you-mean.
        """
        ids = list(self.selection if ids is None else ids)
        items = [self.doc.get(i) for i in ids if self.doc.has(i)]
        if not items:
            return False
        typed = _groups_text(value)
        before = self.doc.groups()
        if len(items) == 1:
            self.doc.update(items[0]["id"], groups=typed)
            note = (t("note.groups", groups=", ".join(_quote_group(g) for g in typed))
                    if typed else t("note.no_groups"))
        else:
            common = shared_groups(items)
            added = [g for g in typed if g not in common]
            removed = [g for g in common if g not in typed]
            parts = []
            for g in added:
                count = sum(1 for it in items if g not in it["groups"])
                parts.append(t("note.group_added", name=g, items=_items(count)))
            for g in removed:
                parts.append(t("note.group_removed", name=g, items=_items(len(items))))
            for it in items:
                groups = [g for g in it["groups"] if g not in removed]
                groups += [g for g in added if g not in groups]
                self.doc.update(it["id"], groups=groups)
            note = " · ".join(parts)
        if not self.history.commit():
            return False
        # A likely typo leads: a long note is cut at the status bar's end.
        hints = [t("note.new_group", name=g) + did_you_mean(g, before)
                 for g in typed if g not in before and did_you_mean(g, before)]
        note = " · ".join(hints + ([note[:1].upper() + note[1:]] if note else []))
        self.message = note or None
        return True

    def move_selection_to(self, axis: str, value: float,
                          ids: Optional[List[int]] = None) -> bool:
        """Move the unlocked items among ``ids`` (default: the selection) so the
        center of their bounding box has ``axis`` (``"x"`` / ``"y"``) = ``value``.
        One undo step (the panel's X / Y for several items)."""
        ids = list(self.selection if ids is None else ids)
        movable = [self.doc.get(i) for i in ids if self.doc.has(i) and not self.doc.get(i)["locked"]]
        box = geo.union_aabb(movable)
        if box is None:
            return False
        try:
            value = float(value)
        except (TypeError, ValueError) as e:
            self.message = str(e)
            return False
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        dx = value - cx if axis == "x" else 0.0
        dy = value - cy if axis == "y" else 0.0
        for it in movable:
            self.doc.update(it["id"], **geo.translate(it, dx, dy))
        return self.history.commit()

    def set_size(self, width: float, height: float) -> bool:
        try:
            self.doc.set_size(width, height)
        except (TypeError, ValueError) as e:
            self.message = str(e)
            return False
        self.history.commit()
        return True

    # -- view --------------------------------------------------------------------------
    def zoom_wheel(self, steps: float, x: float, y: float) -> None:
        if self.viewport is not None and steps:
            self.viewport.zoom_about(1.1 ** steps, x, y)

    def fit_view(self) -> None:
        if self.viewport is None:
            return
        w, h = self.doc.size
        box = geo.union_aabb(self.doc.items)
        area = (0.0, 0.0, w, h)
        if box is not None:
            area = (min(area[0], box[0]), min(area[1], box[1]),
                    max(area[2], box[2]), max(area[3], box[3]))
        self.viewport.fit(area)

    def actual_size(self) -> None:
        """Zoom to 100% (1 design unit = 1 screen unit), keeping the middle of
        the view where it is."""
        if self.viewport is not None:
            self.viewport.actual_size()

    def replace_image(self, item_id: int, file: str, pixel_size: Tuple[float, float]) -> bool:
        """Another file for an image item: same center, angle and height;
        the width follows the new picture's proportions. One undo step."""
        item = self.doc.get(item_id)
        pw, ph = pixel_size
        height = item["height"]
        width = height * pw / ph if ph > 0 else item["width"]
        try:
            self.doc.update(item_id, file=file, width=width, height=height)
        except (TypeError, ValueError) as e:
            self.message = str(e)
            return False
        self.history.commit()
        return True

    # -- cursor ------------------------------------------------------------------------
    def cursor(self, x: float, y: float, *, space: bool = False) -> str:
        """``arrow`` / ``move`` / ``cross`` / ``rotate`` / ``ew`` / ``ns`` / ``nesw`` / ``nwse``."""
        standby = self.select_standby
        if self.tool == "hand" and self.gesture is None and not standby:
            return "move"
        g = self.gesture
        if g is not None:
            kind = g["kind"]
            if kind in ("pan", "move", "press"):
                return "move"
            if kind in ("band", "create", "place"):
                return "cross"
            if kind in ("rotate", "group_rotate"):
                return "rotate"
            if kind == "resize":
                return geo.resize_cursor(self.doc.get(g["id"]), g["key"])
            if kind == "group_scale":
                return geo.frame_cursor(1.0, 1.0, 0.0, g["signs"])
            return "cross"
        if space:
            return "move"
        if self.tool != "select" and not standby:
            return "cross"
        h = self.handle_at(x, y)
        if h is not None:
            if h.role in ("rotate", "group_rotate"):
                return "rotate"
            if h.role == "resize":
                return geo.resize_cursor(self.single(), h.key)
            if h.role == "group_resize":
                return geo.frame_cursor(1.0, 1.0, 0.0, h.key)
            return "cross"
        return "move" if self.items_at(x, y) else "arrow"


def _center(item: Dict[str, Any]) -> geo.Pt:
    if "center" in item:
        return tuple(item["center"])
    x0, y0, x1, y1 = geo.aabb(item)
    return (x0 + x1) / 2, (y0 + y1) / 2


def shared_groups(items: List[Dict[str, Any]]) -> List[str]:
    """The groups every item has, in the first item's order."""
    if not items:
        return []
    return [g for g in items[0]["groups"] if all(g in it["groups"] for it in items[1:])]


def partial_groups(items: List[Dict[str, Any]]) -> List[str]:
    """Groups some of the items have but not all, in first-use order."""
    common = set(shared_groups(items))
    out: List[str] = []
    for it in items:
        for g in it["groups"]:
            if g not in common and g not in out:
                out.append(g)
    return out


def _quote_group(name: str) -> str:
    """A group name as a note shows it: «…» when it holds a space, so
    ``moving enemies`` reads as one group, not two."""
    return f"«{name}»" if any(c.isspace() for c in name) else name


def _items(count: int) -> str:
    return t("note.item_one") if count == 1 else t("note.item_many", count=count)


def _groups_text(value: Any) -> List[str]:
    """The Groups field's text as names. "," separates them, and so does ";"
    (the list separator where "," is the decimal one, as in pt-BR); the field
    and the note then show the result with commas."""
    if isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = re.split(r"[,;]", str(value))
    out: List[str] = []
    for p in parts:
        p = str(p).strip()
        if p and p not in out:
            out.append(p)
    return out
