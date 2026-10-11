"""
box.py — smoke: Box / Grid / box= fit / graphic.box / canvas parents.

Rect draws. Box only measures. Drag corner Anchors on Stamp; sliders carve a
grid; Stamp drops Graphics into cells. Board clicks use cell_at. A/S pages
cover the rest of the surface.

Pages (A/S)
-----------
  Stamp     panel.box + inset / grid / gap + stamp (live overlay; is_collapsed)
  Board     checker + cell_at / click / col_index / neighbor
  Fit       fill vs inscribe vs Sprite contain vs size override vs Text
  Parents   game_view / ui_view / playfield + @leave_playfield (arrows pan)
  Bands     strip inside + beside outside (rotated zone)
  Oriented  rotated grid + cell_at / contains_point + constructors + geom

Usage
-----
    python scripts/smoke/box.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud, apply_camera, SAFE_BOTTOM

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — Box / placement")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="Box / placement",
    expect="Drag Anchors / Angle / wheel → overlay re-reads panel.box; Stamp snapshots; is_collapsed on remainder",
    keys="A/S page  ·  sliders  ·  Angle / wheel on panel  ·  Stamp/Clear  ·  drag Anchors",
    status="ready",
    show_aux=True,
)

CONTENT_X = 340.0
CONTENT_CX = (CONTENT_X + W) * 0.5
CONTENT_CY = 390.0

_SHEET = Path(__file__).resolve().parents[2] / "examples" / "media" / "shooter" / "sheet.xml"
space = Sheet(str(_SHEET))

STAMP_KINDS = (
    "Rect fill",
    "Ellipse fill",
    "Circle inscribe",
    "Square inscribe",
    "Hexagon inscribe",
    "Triangle inscribe",
    "Sprite contain",
    "Sprite height=36",
    "Circle radius=14",
)

st.cols = 6.0
st.rows = 3.0
st.margin = 16.0
st.gap_x = 10.0
st.gap_y = 10.0
st.cell_pad = 4.0
st.kind = STAMP_KINDS[0]
st.overlay = True
st.angle = 0.0

_PAGES: list = []
_owned: list = []
_page_i = 0
_panel = None
_grid = None
_overlay: list = []
_stamps: list = []
_highlight = None
_frustum = None
_piece = None
_leaver = None
_zone = None
_probe_line = None
_beads: list = []
_closest = None
_hover_i = -1
_panel_outline = None
_panel_a1 = None
_panel_a2 = None
_applied_angle = 0.0
_spine_box = None
_spine_outline = None


def _page(name: str, expect: str, keys: str):
    def deco(fn):
        _PAGES.append((name, expect, keys, fn))
        return fn

    return deco


def _track(obj):
    _owned.append(obj)
    return obj


def _cap(text: str, x: float, y: float, *, size: int = 14) -> None:
    _track(
        Text(
            text=text,
            top_left=(x, y + 15),
            font_size=size,
            color=Color(0.7, 0.75, 0.85, 1),
        )
    )


def _world_cap(text: str, pos, *, size: int = 13) -> None:
    _track(
        Text(
            text=text,
            center=pos,
            font_size=size,
            color=Color(0.78, 0.84, 0.94, 1),
        )
    )


def _outline(region, color, *, width=2.0):
    r = Rect(box=region)
    r.fill = None
    r.line = Color(color) if not isinstance(color, Color) else color
    r.line_width = width
    r.clickable = False
    return _track(r)


def _cols() -> int:
    return max(1, int(round(float(st.cols))))


def _rows() -> int:
    return max(1, int(round(float(st.rows))))


def _layout_grid(region: Box):
    try:
        m = float(st.margin)
        inner = region if m <= 0.0 else region.inset(m)
        gx, gy = float(st.gap_x), float(st.gap_y)
        gap = (gx, gy) if abs(gx - gy) > 1e-9 else gx
        return inner.grid(_cols(), _rows(), gap=gap)
    except (ValueError, TypeError) as e:
        hud.status = f"{type(e).__name__}: {e}"
        return None


def _stamp_into(cell: Box):
    pad = float(st.cell_pad)
    region = cell if pad <= 0.0 else cell.inset(pad)
    kind = str(st.kind)
    if kind == "Rect fill":
        r = Rect(box=region, color="steel blue", corner_radius=10)
    elif kind == "Ellipse fill":
        r = Ellipse(box=region, color="tomato")
    elif kind == "Circle inscribe":
        r = Circle(box=region, color="gold")
    elif kind == "Square inscribe":
        r = Square(box=region, color="sea green", corner_radius=8)
    elif kind == "Hexagon inscribe":
        r = RegularPolygon(box=region, n=6, color="medium orchid")
    elif kind == "Triangle inscribe":
        r = EquilateralTriangle(box=region, color="orange")
    elif kind == "Sprite contain":
        r = Sprite(space, frame="playerShip1_blue.png", box=region, art_angle=90)
    elif kind == "Sprite height=36":
        r = Sprite(space, frame="ufoBlue.png", box=region, height=36)
    elif kind == "Circle radius=14":
        r = Circle(box=region, radius=14, color="cyan")
    else:
        r = Rect(box=region, color="gray", corner_radius=8)
    _stamps.append(r)
    _track(r)
    # Remainder after inset / gap: region and/or drawable may have no interior.
    if region.is_collapsed or getattr(r, "is_collapsed", False):
        pin = _track(
            Text(
                text="collapsed",
                center=region.center,
                font_size=11,
                color=Color(1.0, 0.55, 0.35, 1),
            )
        )
        _stamps.append(pin)
    return r


def _clear_stamps():
    for o in list(_stamps):
        try:
            if getattr(o, "is_alive", True):
                o.destroy()
        except Exception:
            pass
    _stamps.clear()
    hud.status = "stamps cleared"


def stamp_cells():
    if _panel is None or _page_i != 0:
        hud.status = "Stamp is for the Stamp page"
        return
    g = _layout_grid(_panel.box)
    if g is None:
        return
    _clear_stamps()
    n_cell_collapsed = 0
    n_region_collapsed = 0
    n_graphic_collapsed = 0
    for cell in g:
        if cell.is_collapsed:
            n_cell_collapsed += 1
        pad = float(st.cell_pad)
        region = cell if pad <= 0.0 else cell.inset(pad)
        if region.is_collapsed:
            n_region_collapsed += 1
        graphic = _stamp_into(cell)
        if getattr(graphic, "is_collapsed", False):
            n_graphic_collapsed += 1
    bits = [
        f"stamped {len(g)} × {st.kind}",
        f"from panel.box",
    ]
    if n_cell_collapsed or n_region_collapsed or n_graphic_collapsed:
        bits.append(
            f"is_collapsed  cells={n_cell_collapsed}  "
            f"regions(pad)={n_region_collapsed}  graphics={n_graphic_collapsed}"
        )
    else:
        bits.append("none collapsed")
    hud.status = "  ·  ".join(bits)


def try_getitem():
    g = Box(center=(0, 0), width=40, height=40).grid(2, 2)
    try:
        _ = g[0, 0]
        hud.status = "UNEXPECTED: g[0, 0] succeeded"
    except TypeError as e:
        hud.status = str(e)


def try_empty_box():
    try:
        Box()
        hud.status = "UNEXPECTED: Box() succeeded"
    except ValueError as e:
        hud.status = str(e)


def _on_board_click(_shape):
    global _piece
    if _grid is None:
        return
    cell = _grid.cell_at(mouse.x, mouse.y)
    if cell is None:
        hud.status = "click in a gap or outside the grid"
        return
    col, row = cell.col_index, cell.row_index
    flat = row * _grid.col_count + col
    note = f"cell({col}, {row})  flat={flat}  g.cell({flat})"
    if col + 1 < _grid.col_count:
        nb = _grid.cell(col + 1, row)
        note += f"  neighbor → ({nb.col_index}, {nb.row_index})"
    hud.status = note
    if _piece is not None and getattr(_piece, "is_alive", False):
        _piece.center = cell.center
    else:
        _piece = _track(
            Sprite(space, frame="ufoYellow.png", box=cell, height=40)
        )


@leave_playfield("leaver")
def _on_leave(shot):
    hud.status = f"@leave_playfield  destroyed {type(shot).__name__}"
    shot.destroy()


def _wrap_angle(deg: float) -> float:
    return (float(deg) + 180.0) % 360.0 - 180.0


def _angle_delta(from_deg: float, to_deg: float) -> float:
    return (float(to_deg) - float(from_deg) + 180.0) % 360.0 - 180.0


def _rotate_panel_to(target_deg: float) -> None:
    """Rotate corner Anchors about their midpoint and match Rect.angle."""
    global _applied_angle
    if _panel_a1 is None or _panel_a2 is None:
        return
    if not getattr(_panel_a1, "is_alive", False) or not getattr(_panel_a2, "is_alive", False):
        return
    target = _wrap_angle(target_deg)
    delta = _angle_delta(_applied_angle, target)
    if abs(delta) > 1e-6:
        cx = (float(_panel_a1.x) + float(_panel_a2.x)) * 0.5
        cy = (float(_panel_a1.y) + float(_panel_a2.y)) * 0.5
        rad = math.radians(delta)
        cos_a, sin_a = math.cos(rad), math.sin(rad)

        def _spin(anchor):
            dx = float(anchor.x) - cx
            dy = float(anchor.y) - cy
            anchor._takein((cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a))

        _spin(_panel_a1)
        _spin(_panel_a2)
    if _panel is not None and getattr(_panel, "is_alive", False):
        _panel.angle = target
    _applied_angle = target
    if abs(float(st.angle) - target) > 1e-3:
        st.angle = target


def _sync_from_box(rect, region: Box) -> None:
    if rect is None or not getattr(rect, "is_alive", False):
        return
    rect.center = region.center
    rect.width = float(region.width)
    rect.height = float(region.height)
    rect.angle = float(region.angle)


def _clear():
    global _panel, _grid, _highlight, _frustum, _piece, _leaver
    global _zone, _probe_line, _closest, _hover_i
    global _panel_outline, _panel_a1, _panel_a2, _applied_angle
    global _spine_box, _spine_outline
    _clear_stamps()
    for o in reversed(list(_owned)):
        try:
            if hasattr(o, "destroy") and getattr(o, "is_alive", True):
                o.destroy()
        except Exception:
            pass
    _owned.clear()
    _overlay.clear()
    _beads.clear()
    _panel = None
    _grid = None
    _highlight = None
    _frustum = None
    _piece = None
    _leaver = None
    _zone = None
    _probe_line = None
    _closest = None
    _hover_i = -1
    _panel_outline = None
    _panel_a1 = None
    _panel_a2 = None
    _applied_angle = 0.0
    _spine_box = None
    _spine_outline = None
    canvas.reset_view()


def _make_overlay_cell():
    r = Rect(center=(0, 0), width=10, height=10)
    r.fill = None
    r.line = Color(0.45, 0.85, 1.0, 0.75)
    r.line_width = 1.5
    r.clickable = False
    return _track(r)


def _sync_overlay(grid: Grid | None):
    global _hover_i
    show = bool(st.overlay) and grid is not None
    n = len(grid) if show else 0
    while len(_overlay) < n:
        _overlay.append(_make_overlay_cell())
    hover = -1
    if show:
        hit = grid.cell_at(mouse.x, mouse.y)
        if hit is not None:
            hover = hit.row_index * grid.col_count + hit.col_index
    for i, r in enumerate(_overlay):
        if not getattr(r, "is_alive", True):
            continue
        if i < n:
            cell = grid.cell(i)
            r.visible = True
            r.center = cell.center
            r.width = cell.width
            r.height = cell.height
            r.angle = cell.angle
            r.line = (
                Color(1.0, 0.85, 0.3, 1)
                if i == hover
                else Color(0.45, 0.85, 1.0, 0.75)
            )
        else:
            r.visible = False
    _hover_i = hover


def _spawn_leaver():
    global _leaver
    _leaver = _track(
        Circle(center=(W - 80, H * 0.45), radius=16, group="leaver", color="gold")
    )


# --- widgets (auto-stack under the HUD) --------------------------------------
ui.gap()
ui.gap()
cols_sl = Slider(
    st["cols"], label="Columns", show_value=True, only_int=True,
    min_value=1.0, max_value=12.0,
)
Slider(
    st["rows"], label="Rows", show_value=True, only_int=True,
    min_value=1.0, max_value=8.0,
)
Slider(st["margin"], label="Inset", show_value=True, min_value=0.0, max_value=48.0)
Slider(st["gap_x"], label="Gap X", show_value=True, min_value=0.0, max_value=40.0)
Slider(st["gap_y"], label="Gap Y", show_value=True, min_value=0.0, max_value=40.0)
Slider(st["cell_pad"], label="Cell pad", show_value=True, min_value=0.0, max_value=24.0)
Slider(st["angle"], label="Angle °", show_value=True, min_value=-180.0, max_value=180.0)
DropDown(st["kind"], options=list(STAMP_KINDS))
Button(label="Stamp cells", on_click=stamp_cells)
Button(label="Clear stamps", on_click=_clear_stamps)

ui.stack_origin(cols_sl.box.top_right + (16, 0))
CheckBox(st["overlay"], label="Live overlay")
Button(label="Raise g[0, 0]", on_click=try_getitem)
Button(label="Raise Box()", on_click=try_empty_box)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@_page(
    "Stamp",
    "Drag Anchors / Angle / pad. Overlay re-reads .box. Stamp: raise Cell pad or Gap until is_collapsed.",
    "A/S page  ·  drag Anchors  ·  Angle / wheel  ·  Stamp / SPACE  ·  Clear  ·  watch status",
)
def _p_stamp():
    global _panel, _grid, _panel_outline, _panel_a1, _panel_a2, _applied_angle
    _panel_a1 = _track(Anchor(CONTENT_CX - 220, CONTENT_CY - 130))
    _panel_a2 = _track(Anchor(CONTENT_CX + 220, CONTENT_CY + 130))
    _panel = _track(Rect(p1=lambda: _panel_a1, p2=lambda: _panel_a2, color="sienna"))
    _panel.fill = Color(0.55, 0.36, 0.22, 0.35)
    _panel.clickable = False
    _applied_angle = 0.0
    _rotate_panel_to(float(st.angle))
    same = Box.from_graphic(_panel)
    _panel_outline = _outline(_panel.box, Color(0.95, 0.82, 0.45, 0.9), width=3)
    _cap("graphic.box is a snapshot — overlay re-reads it each frame; Stamp / box= do not", CONTENT_X, H - 148)
    _cap(
        "Row 0 is visual top.  Raise Cell pad / Gap → remainder; Stamp reports is_collapsed",
        CONTENT_X,
        H - 170,
    )
    _grid = _layout_grid(_panel.box)
    _sync_overlay(_grid)
    b = _panel.box
    hud.status = (
        f"Box is Entity? {isinstance(b, Entity)}  "
        f"Box(panel) w={float(same.width):.0f}  "
        f"angle={float(b.angle):.0f}°  col_index={b.col_index}  "
        f"is_collapsed={b.is_collapsed}"
    )


@_page(
    "Board",
    "Click a square → cell_at names (col, row). Hover highlights. Piece follows the pick.",
    "A/S page  ·  click squares / gaps  ·  sliders resize the board",
)
def _p_board():
    global _panel, _grid, _highlight
    _panel = _track(
        Rect(
            center=(CONTENT_CX, CONTENT_CY),
            width=560,
            height=560,
            color="sienna",
            corner_radius=8,
        )
    )
    _panel.on_click = _on_board_click
    g = _layout_grid(_panel.box)
    _grid = g
    if g is None:
        return
    for cell in g:
        color = "tan" if (cell.col_index + cell.row_index) % 2 == 0 else "sienna"
        sq = _track(Rect(box=cell, color=color))
        sq.on_click = _on_board_click
        if cell.row_index == 0 and cell.col_index == 0:
            _world_cap("row 0", (cell.center.x, cell.top + 16), size=12)
    same_cell = g.rows[0][0] is g.cols[0][0]
    _cap(
        f"g.rows[0][0] is g.cols[0][0] → {same_cell}  "
        f"(lists; counts are row_count / col_count)",
        CONTENT_X,
        H - 192,
    )
    _highlight = _outline(g.cell(0, 0), Color(1.0, 0.85, 0.3, 1), width=3)
    _highlight.visible = False
    _cap(
        f"panel.box.inset.grid  {g.col_count}×{g.row_count}  "
        f"len={len(g)}  rows={len(g.rows)}  cols={len(g.cols)}",
        CONTENT_X,
        H - 148,
    )
    _cap("Click Graphic, look up with grid.cell_at — Box itself is not clickable.", CONTENT_X, H - 170)
    hud.status = "click a square…"


@_page(
    "Fit",
    "Rect/Ellipse fill the cell; Circle/Square/N-gon inscribe; Sprite contains; size= centers only.",
    "A/S page  ·  compare fill vs inscribe vs contain  ·  HUD Text(box=)",
)
def _p_fit():
    samples = (
        ("Rect fill", lambda c: Rect(box=c, color="sienna", corner_radius=12)),
        ("Ellipse fill", lambda c: Ellipse(box=c, color="tomato")),
        ("Circle inscr.", lambda c: Circle(box=c, color="gold")),
        ("Square inscr.", lambda c: Square(box=c, color="sea green", corner_radius=8)),
        ("Hex inscr.", lambda c: RegularPolygon(box=c, n=6, color="medium orchid")),
        ("Sprite contain", lambda c: Sprite(space, frame="playerShip1_blue.png", box=c, art_angle=90)),
        ("Sprite h=36", lambda c: Sprite(space, frame="ufoGreen.png", box=c, height=36)),
        ("Circle r=14", lambda c: Circle(box=c, radius=14, color="cyan")),
        ("Triangle inscr.", lambda c: EquilateralTriangle(box=c, color="orange")),
        ("Rect + pad", lambda c: Rect(box=c.inset(8), color="steel blue", corner_radius=10)),
    )
    zone = Box(center=(CONTENT_CX, CONTENT_CY + 10), width=980, height=520)
    _outline(zone, Color(0.35, 0.4, 0.5, 0.8), width=1.5)
    g = zone.inset(max(8.0, float(st.margin))).grid(5, 2, gap=18)
    for i, cell in enumerate(g):
        label, factory = samples[i]
        _outline(cell, Color(1, 1, 1, 0.22), width=1)
        _track(factory(cell))
        _world_cap(label, (cell.center.x, cell.bottom - 18), size=12)
    hud_cell = Box(p1=(W - 430, SAFE_BOTTOM + 10), p2=(W - 24, SAFE_BOTTOM + 58))
    _track(Rect(box=hud_cell, layer="ui", color=Color(0.18, 0.32, 0.5, 0.75), corner_radius=8))
    _track(
        Text(
            "Text(box=) view pin",
            box=hud_cell,
            layer="ui",
            font_size=15,
        )
    )
    _cap("box= is its own family — mix with center=/width= raises (see tests).", CONTENT_X, H - 148)
    hud.status = "fill vs inscribe vs contain vs center+size"


@_page(
    "Parents",
    "Gold band carved at setup stays in the world. Cyan frustum follows the camera. HUD does not.",
    "A/S page  ·  arrows pan  ·  Shift+←/→ rotate  ·  Shift+↑/↓ zoom  ·  R reset",
)
def _p_parents():
    global _frustum
    gv = canvas.game_view
    band = gv.inset(48).grid(1, 5).cell(0, 0)
    _track(Rect(box=band, color=Color(1.0, 0.82, 0.28, 0.28)))
    _world_cap("carved game_view.grid(1,5).cell(0,0) at setup — world-fixed", band.center)
    pf_box = canvas.playfield.inset(0)
    _outline(pf_box, Color(0.95, 0.35, 0.75, 0.9), width=3)
    halo = canvas.playfield.outset(40)
    _outline(halo, Color(1.0, 0.55, 0.2, 0.75), width=2)
    safe = canvas.playfield.inset(80)
    _outline(safe, Color(0.4, 0.9, 0.55, 0.85), width=2)
    pad_before = canvas.playfield.pad
    _ = canvas.playfield.inset(80)
    pad_after = canvas.playfield.pad
    _frustum = _outline(gv, Color(0.35, 0.85, 1.0, 0.95), width=3)
    canvas.zoom_to(0.62, about=gv.center)
    _spawn_leaver()
    strip = canvas.ui_view.inset(16).grid(1, 12).cell(0, 10)
    _track(Rect(box=strip, layer="ui", color=Color(0.12, 0.28, 0.42, 0.8), corner_radius=8))
    _track(
        Text(
            "ui_view HUD — magenta=playfield  ·  orange=outset(40)  ·  green=inset(80)",
            box=strip,
            layer="ui",
            font_size=14,
        )
    )
    _cap(
        f"playfield is Box? {isinstance(canvas.playfield, Box)}  "
        f"outset returns Box? {isinstance(halo, Box)}  "
        f"pad unchanged {pad_before}→{pad_after}  bounds is alias? "
        f"{canvas.bounds is canvas.playfield}",
        CONTENT_X,
        H - 148,
    )
    hud.status = "pan/zoom — cyan follows frustum; gold band stays; HUD stays"


@_page(
    "Bands",
    "strip = inside edge band; beside = outside neighbor. Local sides keep angle.",
    "A/S page",
)
def _p_bands():
    zone = Box(center=(CONTENT_CX, CONTENT_CY), width=360, height=220, angle=28)
    _outline(zone, Color(0.95, 0.82, 0.45, 1), width=3)
    _track(Rect(box=zone, color=Color(0.18, 0.22, 0.28, 0.35), corner_radius=4))
    top = zone.strip("top", 48)
    left = zone.strip("left", 56)
    right = zone.beside("right", width=90)
    bottom = zone.beside("bottom", height=44, gap=12)
    _track(Rect(box=top, color=Color(0.35, 0.75, 1.0, 0.45), corner_radius=4))
    _track(Rect(box=left, color=Color(0.45, 0.9, 0.55, 0.45), corner_radius=4))
    _track(Rect(box=right, color=Color(1.0, 0.55, 0.35, 0.5), corner_radius=4))
    _track(Rect(box=bottom, color=Color(0.95, 0.45, 0.75, 0.5), corner_radius=4))
    _world_cap("strip top", top.center, size=12)
    _world_cap("strip left", left.center, size=12)
    _world_cap("beside right", right.center, size=12)
    _world_cap("beside bottom gap=12", bottom.center, size=12)
    _cap(
        "cyan/green = strip (inside)  ·  orange/magenta = beside (outside)  ·  zone angle=28°",
        CONTENT_X,
        H - 148,
    )
    hud.status = "strips stay inside; beside stays outside — local edges follow angle"


@_page(
    "Oriented",
    "Rotated grid: cell_at / contains_point use the local frame. Constructors along the bottom.",
    "A/S page  ·  move the mouse  ·  drag spine Anchors  ·  Raise g[0,0] still works",
)
def _p_oriented():
    global _zone, _probe_line, _closest, _grid, _spine_box, _spine_outline
    _zone = Box(center=(CONTENT_CX, 470), width=520, height=280, angle=28)
    _grid = _zone.grid(6, 4, gap=12)
    _outline(_zone, Color(0.95, 0.82, 0.45, 1), width=3)
    for cell in _grid:
        tint = 0.22 + 0.08 * ((cell.col_index + cell.row_index) % 3)
        r = _track(Rect(box=cell, color=Color(0.25, 0.45, tint + 0.35, 0.85), corner_radius=6))
        r.clickable = False
    _probe_line = _track(
        Line(p1=(CONTENT_CX - 360, 470), p2=(CONTENT_CX + 360, 470), color="white")
    )
    _probe_line.line_width = 2
    for _ in range(4):
        bead = _track(Circle(center=(0, 0), radius=6, color="white"))
        bead.visible = False
        _beads.append(bead)
    _closest = _track(Circle(center=(0, 0), radius=8, color="lime"))
    # Constructor gallery (same models as Rect).
    models = [
        ("CENTER_WH", Box(center=(400, 150), width=130, height=56)),
        ("TOP_LEFT_WH", Box(top_left=(500, 178), width=130, height=56)),
        ("CORNER_CORNER", Box(p1=(660, 122), p2=(790, 178))),
        ("POINT_VEC", Box(p1=(820, 122), vec=Vec2(130, 56))),
    ]
    for name, b in models:
        _outline(b, "cyan", width=2)
        _world_cap(name, (b.center.x, b.bottom - 16), size=11)
    sa = _track(Anchor(1080, 150))
    sb = _track(Anchor(1240, 150))
    _spine_box = Box(p1=lambda: sa, p2=lambda: sb, height=40, anchor="square")
    _spine_outline = _outline(_spine_box, "gold", width=2)
    _world_cap("SPINE square", (1160, 106), size=11)
    _cap("cell_at inverse-transforms first.  Lime = closest_point(Box, mouse).  White = intersections.", CONTENT_X, H - 148)
    hud.status = "move the mouse over the rotated grid"


def _rebuild():
    _clear()
    name, expect, keys, fn = _PAGES[_page_i]
    hud.title = f"Box / placement — {name}  ({_page_i + 1}/{len(_PAGES)})"
    hud.expect = expect
    hud.keys = keys
    fn()


def setup(_canvas):
    _rebuild()


def update(dt):
    global _page_i, _leaver, _grid
    if keyp.once("A"):
        _page_i = (_page_i - 1) % len(_PAGES)
        _rebuild()
        return
    if keyp.once("S"):
        _page_i = (_page_i + 1) % len(_PAGES)
        _rebuild()
        return

    name = _PAGES[_page_i][0]

    if name == "Stamp":
        if keyp.once("SPACE"):
            stamp_cells()
        if _panel is not None and getattr(_panel, "is_alive", False):
            _rotate_panel_to(float(st.angle))
            _sync_from_box(_panel_outline, _panel.box)
            _grid = _layout_grid(_panel.box)
            _sync_overlay(_grid)
            if _grid is not None:
                hit = _grid.cell_at(mouse.x, mouse.y)
                inside = _panel.box.contains_point(mouse.x, mouse.y)
                ang = float(_panel.box.angle)
                pad = float(st.cell_pad)
                if hit is None:
                    hud.aux = (
                        f"cell_at=None  contains_point={inside}  "
                        f"angle={ang:.0f}°  overlay={'on' if st.overlay else 'off'}  "
                        f"panel.is_collapsed={_panel.box.is_collapsed}"
                    )
                else:
                    region = hit if pad <= 0.0 else hit.inset(pad)
                    hud.aux = (
                        f"cell({hit.col_index}, {hit.row_index})  "
                        f"contains_point={inside}  "
                        f"angle={ang:.0f}°  "
                        f"{hit.width:.0f}×{hit.height:.0f}  "
                        f"cell.is_collapsed={hit.is_collapsed}  "
                        f"pad→is_collapsed={region.is_collapsed}"
                    )

    elif name == "Board":
        if _grid is not None and _highlight is not None:
            hit = _grid.cell_at(mouse.x, mouse.y)
            if hit is None:
                _highlight.visible = False
                hud.aux = "cell_at=None (gap or outside)"
            else:
                _highlight.visible = True
                _highlight.center = hit.center
                _highlight.width = hit.width
                _highlight.height = hit.height
                hud.aux = (
                    f"hover cell({hit.col_index}, {hit.row_index})  "
                    f"g.cell({hit.row_index * _grid.col_count + hit.col_index})  "
                    f"is_collapsed={hit.is_collapsed}"
                )

    elif name == "Parents":
        apply_camera(dt, about=(W * 0.5, H * 0.5))
        if keyp.once("R"):
            canvas.reset_view()
            canvas.zoom_to(0.62, about=canvas.game_view.center)
            hud.status = "view reset"
        gv = canvas.game_view
        if _frustum is not None and getattr(_frustum, "is_alive", False):
            _frustum.center = gv.center
            _frustum.width = gv.width
            _frustum.height = gv.height
        if _leaver is None or not getattr(_leaver, "is_alive", False):
            _spawn_leaver()
        else:
            _leaver.move_by(220 * dt, 0)
        hud.aux = (
            f"game_view center=({float(gv.center.x):.0f}, {float(gv.center.y):.0f})  "
            f"ui_view {float(canvas.ui_view.width):.0f}×{float(canvas.ui_view.height):.0f}"
        )

    elif name == "Oriented":
        if _zone is not None and _grid is not None:
            inside = _zone.contains_point(mouse.x, mouse.y)
            hit = _grid.cell_at(mouse.x, mouse.y)
            if hit is None:
                hud.aux = f"contains_point={inside}  cell_at=None"
            else:
                hud.aux = (
                    f"contains_point={inside}  "
                    f"cell({hit.col_index}, {hit.row_index}) angle={float(hit.angle):.0f}°"
                )
            if _probe_line is not None:
                hits = intersections(_probe_line, _zone)
                for i, bead in enumerate(_beads):
                    if i < len(hits):
                        bead.visible = True
                        bead.center = hits[i]
                    else:
                        bead.visible = False
            if _closest is not None:
                _closest.center = closest_point(_zone, (mouse.x, mouse.y))
            if _spine_box is not None:
                _sync_from_box(_spine_outline, _spine_box)


def on_mouse_scroll(_xoffset, yoffset):
    if _PAGES[_page_i][0] != "Stamp":
        return
    if _panel is None or not getattr(_panel, "is_alive", False):
        return
    if not _panel.box.contains_point(mouse.x, mouse.y):
        return
    st.angle = _wrap_angle(float(st.angle) + float(yoffset) * 8.0)


run()
