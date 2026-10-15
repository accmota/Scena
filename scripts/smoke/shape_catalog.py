"""
shape_catalog.py — smoke: paged constructor catalog for every shape family.

One page per family (Line, Circle, Ellipse, Rect, Square + RegularPolygon,
Triangle, Concave, Track, Polygon). A/S cycles pages. H / P toggle handles / points.
C toggles collider outlines (starts ON). SPACE pauses spin. R resets spin speed.
Constructor points are always-on Anchors; drag them to reshape.
Hold a shape and scroll to rotate (when the model's heading parts are free).
The Unlink Anchors button drops those formulas so every shape can wheel-rotate.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — shape catalog")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="Shape catalog",
    expect="A/S pages every constructor model",
    keys="A/S page  ·  drag Anchors  ·  hold+wheel rotate  ·  Unlink Anchors  ·  SPACE pause  ·  C colliders  ·  H handles  ·  P points  ·  R reset spin",
    status="outlines ON",
)

st.create("spin", initial=0.0)
st.create("spin_speed", initial=45.0)
st.create("paused", initial=0)

# Sliders sit under the HUD band, clear of bottom FPS.
Slider(st["spin_speed"], min_value=0.0, max_value=180.0, top_left=(24, H - 92), width=220)

_owned: list = []
_spin: list[tuple] = []
_wheel: list = []
_page_i = 0
_show_handles = False
_show_points = False
_show_colliders = True
collision.show_colliders(True)


def _cap(text: str, x: float, y: float, *, size: int = 13) -> None:
    """Scene caption — keep clear of top HUD (~110) and bottom FPS (48)."""
    lb = Text(text=text, top_left=(x, y + 15), font_size=size, color=Color(0.7, 0.75, 0.85, 1))
    _owned.append(lb)


def _anchor(x: float, y: float) -> Anchor:
    """Visible construction-point handle. Shapes link *to* it (lambda), never inbound."""
    a = Anchor(x, y)
    _owned.append(a)
    return a


def _track(obj, *, interact: bool = True):
    _owned.append(obj)
    if interact:
        _wheel.append(obj)
    if hasattr(obj, "collidable"):
        try:
            obj.collidable = True
        except Exception:
            pass
    return obj


def _spin_by(shape, factor: float = 1.0):
    """Auto-spin via rotate_by so angle stays free for hold+wheel."""
    _spin.append((shape, factor))
    return shape


def _clear():
    for o in list(_owned):
        try:
            if hasattr(o, "destroy") and getattr(o, "is_alive", True):
                o.destroy()
            elif hasattr(o, "clean_up"):
                o._widget_manager.remove_widget(o)
                o._clean_up()
        except Exception:
            pass
    _owned.clear()
    _spin.clear()
    _wheel.clear()


def _apply_markers():
    for o in _owned:
        # Anchors stay visible; H/P only toggles each shape's own point markers.
        if isinstance(o, Point) or not hasattr(o, "show_handles"):
            continue
        try:
            if _show_handles:
                o.show_handles()
            else:
                o.no_handles()
            if _show_points:
                o.show_points()
            else:
                o.no_points()
        except Exception:
            pass


def _enable_wheel():
    """Hold + wheel after formulas are in. clickable so the press lands."""
    for o in _wheel:
        if not hasattr(o, "wheel_rotate"):
            continue
        try:
            o.wheel_rotate = True
            o.clickable = True
        except LinkedAttributeError:
            pass


def _free_from_anchors():
    """Drop inbound formulas (Anchors, spin, relational) so every shape can rotate."""
    n = 0
    for o in _wheel:
        if not hasattr(o, "unlink_all"):
            continue
        o.unlink_all()
        n += 1
    _enable_wheel()
    armed = sum(1 for o in _wheel if getattr(o, "wheel_rotate", False))
    hud.status = f"unlinked {n} shapes — hold+wheel rotate ({armed} armed)"


Button(label="Unlink Anchors", top_left=(260, H - 92), width=180, on_click=_free_from_anchors)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
PAGES = []


def _page(name: str, expect: str):
    def deco(fn):
        PAGES.append((name, expect, fn))
        return fn

    return deco


@_page("Point + Line", "All LineModel variants; drag Anchors (construction points)")
def _p_line():
    _cap("CENTER_LENGTH_ANGLE (home) / POINT_POINT / POINT_VEC / POINT_DX_DY / POINT_ANGLE_LENGTH", 40, H - 150)
    home_c = _anchor(160, 580)
    home = _track(Line(center=lambda: home_c, length=120, angle=20).set_color("white"))
    home.line_width = 3
    a = _anchor(100, 480)
    b = _anchor(100, 280)
    _track(Line(p1=lambda: a, p2=lambda: b).set_color("red"))
    vec_p = _anchor(220, 480)
    _track(Line(p1=lambda: vec_p, vec=Vec2(200, 40)).set_color("orange"))
    dx_p = _anchor(220, 380)
    _track(Line(p1=lambda: dx_p, dx=200, dy=-50).set_color("gold"))
    ang_p = _anchor(220, 260)
    ang = _track(Line(p1=lambda: ang_p, angle=0.0, length=160).set_color("yellow"))
    # p1 is linked (Anchor); rotate_by would also write p1 — keep angle formula.
    ang["angle"] @= lambda: st.spin

    _cap("PARALLEL_POINT / PARALLEL_DIST / PERPENDICULAR_POINT", 520, H - 150)
    # POINT_ANGLE_LENGTH so angle is Defining (can @= spin).
    ref_p = _anchor(540, 480)
    ref = _track(Line(p1=lambda: ref_p, angle=12.0, length=280).set_color("white"))
    ref["angle"] @= lambda: 12.0 + 0.15 * float(st.spin)
    par_p = _anchor(540, 360)
    _track(Line(p1=lambda: par_p, parallel_to=ref, length=200).set_color("lime"))
    _track(Line(dist=36, parallel_to=ref).set_color("gold"))
    perp_p = _anchor(580, 500)
    _track(Line(p1=lambda: perp_p, perpendicular_to=ref, length=100).set_color("turquoise"))

    _cap("TANGENT_ANGLE / TANGENT_POINT", 900, H - 150)
    circ_c = _anchor(1040, 420)
    circ = _track(Circle(center=lambda: circ_c, radius=70).set_color("cyan"))
    tan_a = _track(Line(circle=circ, at_angle=0.0, length=120).set_color("magenta"))
    tan_a["angle"] @= lambda: st.spin
    ext = _anchor(1220, 520)
    _track(Line(circle=circ, from_point=lambda: ext, side="left").set_color("lime green"))
    _track(Line(circle=circ, from_point=lambda: ext, side="right").set_color("sea green"))


@_page("Circle", "CENTER_RADIUS · CENTER_PERIMETER · TWO_POINTS · arc (pie); drag Anchors")
def _p_circle():
    _cap("CENTER_RADIUS", 80, 620)
    cr_c = _anchor(180, 480)
    _track(Circle(center=lambda: cr_c, radius=70).set_color("red"))

    _cap("CENTER_PERIMETER", 380, 620)
    cp_c = _anchor(420, 480)
    per = _anchor(480, 520)
    _track(Circle(center=lambda: cp_c, perimeter_point=lambda: per).set_color("orange"))

    _cap("TWO_POINTS (diameter)", 680, 620)
    tp_a = _anchor(720, 420)
    tp_b = _anchor(880, 540)
    _track(Circle(p1=lambda: tp_a, p2=lambda: tp_b).set_color("gold"))

    _cap("arc (pie, default) — spins", 1000, 620)
    arc_c = _anchor(1120, 480)
    arc = _track(
        Circle(
            center=lambda: arc_c,
            radius=70,
            angle=130.0,
            spread=60.0,
        ).set_color("yellow")
    )
    arc["angle"] @= lambda: 130.0 + st.spin
    arc["spread"] @= lambda: 5.0 + st.spin/5


@_page("Ellipse", "CENTER_WH · FOCAL_POINTS · FROM_RECT (tracks spinning rect); drag Anchors")
def _p_ellipse():
    _cap("CENTER_WH", 80, 620)
    ew_c = _anchor(200, 480)
    _track(Ellipse(center=lambda: ew_c, width=180, height=90, angle=15).set_color("lime"))

    _cap("FOCAL_POINTS", 420, 620)
    fp1 = _anchor(480, 450)
    fp2 = _anchor(620, 450)
    # FOCAL_POINTS validates foci at construct (no lambda); link after.
    ef = _track(Ellipse(fp1=fp1, fp2=fp2, major_axis=200).set_color("sea green"))
    ef["fp1"] @= lambda: fp1
    ef["fp2"] @= lambda: fp2

    _cap("FROM_RECT (padding=12) — follows gold rect", 780, 620)
    host_c = _anchor(1000, 480)
    host = _track(Rect(center=lambda: host_c, width=200, height=120).set_color("gold"))
    _spin_by(host, 0.4)
    el = _track(Ellipse(from_rect=host, padding=12).set_color("turquoise"))
    el.set_alpha(0.4)


@_page("Rect", "CORNER_CORNER · TOP_LEFT_WH · CENTER_WH · POINT_VEC · SPINE (bottom-right) · corner_radius")
def _p_rect():
    _cap("CORNER_CORNER", 60, 640)
    rcc_a = _anchor(80, 400)
    rcc_b = _anchor(240, 540)
    _track(Rect(p1=lambda: rcc_a, p2=lambda: rcc_b).set_color("red"))

    _cap("TOP_LEFT_WH", 300, 640)
    rtl = _anchor(320, 540)
    _track(Rect(top_left=lambda: rtl, width=160, height=110, angle=12).set_color("orange"))

    _cap("CENTER_WH (spins)", 560, 640)
    rcw = _anchor(640, 470)
    rc = _track(Rect(center=lambda: rcw, width=160, height=100).set_color("gold"))
    _spin_by(rc, 0.5)

    _cap("POINT_VEC", 820, 640)
    rpv = _anchor(840, 400)
    _track(Rect(p1=lambda: rpv, vec=Vec2(160, 90)).set_color("yellow"))

    # SPINE cluster — bottom-right, clear of the models above and of corner_radius.
    _cap("SPINE  p1→p2 + height + anchor", 980, 360)
    _cap('anchor="cap"', 980, 335)
    cap_a = _anchor(1140, 320)
    cap_b = _anchor(1300, 320)
    _track(Rect(p1=lambda: cap_a, p2=lambda: cap_b, height=40, anchor="cap").set_color("lime"))

    _cap('anchor="square"', 980, 268)
    sq_a = _anchor(1160, 245)
    sq_b = _anchor(1300, 245)
    _track(Rect(p1=lambda: sq_a, p2=lambda: sq_b, height=40, anchor="square").set_color("sea green"))

    _cap('anchor="side_left"', 980, 198)
    sl_a = _anchor(1140, 155)
    sl_b = _anchor(1300, 155)
    _track(Rect(p1=lambda: sl_a, p2=lambda: sl_b, height=40, anchor="side_left").set_color("turquoise"))

    _cap('anchor="side_right"', 980, 138)
    sr_a = _anchor(1140, 115)
    sr_b = _anchor(1300, 115)
    _track(Rect(p1=lambda: sr_a, p2=lambda: sr_b, height=40, anchor="side_right").set_color("cyan"))

    _cap("corner_radius (spins)", 60, 280)
    rr_c = _anchor(200, 160)
    rr = _track(
        Rect(center=lambda: rr_c, width=180, height=100, corner_radius=22).set_color("tomato")
    )
    _spin_by(rr, 0.35)


@_page("Square · RegularPolygon", "Square + RegularPolygon models; drag Anchors")
def _p_poly_reg():
    _cap("Square center / top_left", 60, 640)
    sq_c = _anchor(160, 480)
    sq = _track(Square(center=lambda: sq_c, length=100).set_color("turquoise"))
    sq["length"] @= lambda: 100 + 12 * math.sin(math.radians(st.spin))
    sq_tl = _anchor(280, 540)
    _track(Square(top_left=lambda: sq_tl, length=80).set_color("cyan"))

    _cap("corner_radius", 60, 280)
    sq_r = _anchor(160, 200)
    _track(Square(center=lambda: sq_r, length=90, corner_radius=18).set_color("sky blue"))

    _cap("RegularPolygon CENTER_RADIUS / CENTER_SIDE / VERTEX_SIDE", 420, 640)
    pent_c = _anchor(520, 470)
    pent = _track(RegularPolygon(n=5, center=lambda: pent_c, radius=70).set_color("orange"))
    _spin_by(pent)
    hex_c = _anchor(720, 470)
    hex_ = _track(RegularPolygon(n=6, center=lambda: hex_c, side=55).set_color("gold"))
    _spin_by(hex_, -1.0)
    oct_v = _anchor(920, 420)
    _track(RegularPolygon(n=8, vertex=lambda: oct_v, side=40).set_color("yellow"))

    _cap("RegularPolygon box= (fits once)", 420, 280)
    frame = Box(center=(620, 180), width=200, height=150)
    _frame(frame)
    _track(RegularPolygon(n=7, box=frame).set_color("tomato"))


def _frame(box: Box) -> None:
    """Dim Rect over a Box, so a box= fit shows the region it fitted into."""
    fr = _track(Rect(box=box).set_color("white"), interact=False)
    fr.set_alpha(0.15)


@_page("Triangle", "CENTER_RADIUS · CENTER_SIDE · VERTEX_SIDE · base_ratio (static + live) · box=")
def _p_triangle():
    _cap("CENTER_RADIUS (spins)", 60, 640)
    tr_c = _anchor(160, 470)
    tr = _track(Triangle(center=lambda: tr_c, radius=70, angle=90).set_color("lime"))
    _spin_by(tr)

    _cap("CENTER_SIDE  base_ratio=0.6", 290, 640)
    ts_c = _anchor(400, 470)
    _track(Triangle(center=lambda: ts_c, side=120, angle=90, base_ratio=0.6).set_color("sea green"))

    _cap("VERTEX_SIDE  apex on the Anchor", 540, 640)
    tv = _anchor(640, 560)
    _track(Triangle(vertex=lambda: tv, side=120, angle=90, base_ratio=0.8).set_color("turquoise"))

    # Live base_ratio: each model keeps its own inputs while the base changes.
    _cap("base_ratio @= 0.85 + 0.5·sin(spin)", 820, 640)
    _cap("radius: center + apex stay · side: legs stay · vertex: apex + legs stay", 820, 615, size=11)
    ratio = lambda: 0.85 + 0.5 * math.sin(math.radians(st.spin))
    lr_c = _anchor(910, 470)
    lr = _track(Triangle(center=lambda: lr_c, radius=60, angle=90).set_color("gold"))
    lr["base_ratio"] @= ratio
    ls_c = _anchor(1090, 470)
    ls = _track(Triangle(center=lambda: ls_c, side=100, angle=90).set_color("orange"))
    ls["base_ratio"] @= ratio
    lv = _anchor(1270, 550)
    lv_t = _track(Triangle(vertex=lambda: lv, side=100, angle=90).set_color("tomato"))
    lv_t["base_ratio"] @= ratio

    _cap("base_ratio 0.3 · 0.6 · 1 · 1.4 · 1.8  (side=70)", 60, 330)
    for i, r in enumerate((0.3, 0.6, 1.0, 1.4, 1.8)):
        x = 100 + 130 * i
        _track(Triangle(center=(x, 190), side=70, angle=90, base_ratio=r).set_color("yellow green"))
        _cap(f"{r:g}", x - 8, 95, size=11)

    _cap("box= inscribed circle, box angle, keeps base_ratio", 820, 330)
    tall = Box(center=(920, 190), width=150, height=190)
    _frame(tall)
    _track(Triangle(box=tall).set_color("cyan"))
    wide = Box(center=(1180, 190), width=230, height=110, angle=15)
    _frame(wide)
    _track(Triangle(box=wide, base_ratio=0.5).set_color("magenta"))


@_page("Concave", "scoop= corners + edges · rim (static + live) · Rect models · box=; drag Anchors")
def _p_concave():
    _cap("scoop= corner (a quarter out)", 60, 640)
    for i, sc in enumerate(("top_left", "top_right", "bottom_left", "bottom_right")):
        x = 110 + 140 * i
        c = _anchor(x, 490)
        _track(Concave(center=lambda c=c: c, width=110, height=110, scoop=sc).set_color("orange"))
        _cap(sc, x - 45, 405, size=11)

    _cap("scoop= edge middle (a half out)", 660, 640)
    for sc, xy, wh in (
        ("top_center", (760, 540), (160, 80)),
        ("bottom_center", (760, 420), (160, 80)),
        ("left_center", (960, 480), (80, 160)),
        ("right_center", (1080, 480), (80, 160)),
    ):
        c = _anchor(*xy)
        _track(Concave(center=lambda c=c: c, width=wh[0], height=wh[1], scoop=sc).set_color("gold"))
        _cap(sc, xy[0] - 45, xy[1] - wh[1] / 2 - 30, size=11)

    _cap("spins (ellipse scoop)", 1180, 640)
    sp_c = _anchor(1270, 480)
    sp = _track(Concave(center=lambda: sp_c, width=150, height=90, scoop="bottom_right").set_color("yellow"))
    _spin_by(sp, 0.5)

    _cap("rim=(20, 0) quarter-pipe deck", 60, 330)
    rm = _anchor(60, 270)
    _track(Concave(top_left=lambda: rm, width=170, height=170, rim=(20, 0)).set_color("lime"))

    _cap("rim @= live (half-pipe)", 290, 330)
    hp_c = _anchor(410, 180)
    hp = _track(Concave(center=lambda: hp_c, width=240, height=140, scoop="top_center").set_color("sea green"))
    hp["rim"] @= lambda: (0.0, 35.0 + 30.0 * math.sin(math.radians(st.spin)))

    _cap("CORNER_CORNER p1 / p2", 580, 330)
    pa = _anchor(600, 100)
    pb = _anchor(740, 250)
    _track(Concave(p1=lambda: pa, p2=lambda: pb, scoop="top_right").set_color("turquoise"))

    _cap("POINT_VEC", 790, 330)
    pv = _anchor(800, 100)
    _track(Concave(p1=lambda: pv, vec=Vec2(140, 120), scoop="bottom_left", rim=10).set_color("cyan"))

    _cap('SPINE anchor="side_left"', 980, 330)
    s1 = _anchor(1000, 130)
    s2 = _anchor(1160, 170)
    _track(Concave(p1=lambda: s1, p2=lambda: s2, height=90, anchor="side_left").set_color("sky blue"))

    _cap("box= (fits once)", 1200, 330)
    bx = Box(center=(1290, 180), width=150, height=110, angle=-20)
    _frame(bx)
    _track(Concave(box=bx, scoop="top_center").set_color("magenta"))


@_page("Track", "FREE (points / vectors / closed) · CIRCLE · SHAPE · presets; drag Anchors")
def _p_track():
    _cap("FREE points= smooth (white) / smooth=0 (orange)", 60, 640)
    pts = [_anchor(80, 430), _anchor(170, 560), _anchor(260, 440), _anchor(350, 560)]
    _track(Track(points=[lambda a=a: (a.center.x, a.center.y) for a in pts], color="white",
                 line_width=2), interact=False)
    _track(Track(points=[lambda a=a: (a.center.x, a.center.y) for a in pts],
                        smooth=0, color="orange", line_width=2), interact=False)

    _cap("vectors= from start, closed", 440, 640)
    walk = _track(Track(vectors=[(120, 0), (0, 120), (-60, 40), (-60, -40)], start=(470, 420),
                        closed=True, smooth=0.5, color="gold", line_width=2), interact=False)
    # start= is a snapshot; the pose links through center.
    wc = _anchor(walk.center.x, walk.center.y)
    walk["center"] @= lambda: wc

    _cap("CIRCLE Track.circle (center Anchor)", 700, 640)
    cc = _anchor(820, 490)
    _track(Track.circle(radius=75, center=lambda: cc, color="cyan", line_width=2), interact=False)

    _cap("SHAPE Track(rect) follows the spin", 1010, 640)
    host_c = _anchor(1150, 490)
    host = _track(Rect(center=lambda: host_c, width=180, height=100, corner_radius=20).set_color("white"))
    host.set_alpha(0.2)
    _spin_by(host, 0.4)
    _track(Track(host, color="magenta", line_width=3), interact=False)

    _cap("presets: line · arc · eight · star · spiral · wave · shuttle", 60, 330)
    y = 190
    colors = ("red", "orange", "gold", "yellow", "lime", "turquoise", "violet")
    for i, make in enumerate((
        lambda c, **k: Track.line(length=120, angle=30, p1=(c[0] - 52, c[1] - 30), **k),
        lambda c, **k: Track.arc(radius=60, from_angle=0, to_angle=220, center=c, **k),
        lambda c, **k: Track.eight(width=150, height=80, center=c, **k),
        lambda c, **k: Track.star(points=5, radius=65, center=c, **k),
        lambda c, **k: Track.spiral(turns=3, radius=65, center=c, **k),
        lambda c, **k: Track.wave(length=150, amplitude=25, waves=2, start=(c[0] - 75, c[1]), **k),
        lambda c, **k: Track.shuttle(length=120, angle=-30, center=c, **k),
    )):
        _track(make((110 + 190 * i, y), color=colors[i], line_width=2), interact=False)


@_page("Polygon + hub", "Free Polygon; hub Anchor spokes to centers (formula links)")
def _p_hub():
    _cap("Irregular Polygon", 60, 640)
    v0 = _anchor(100, 400)
    v1 = _anchor(220, 420)
    v2 = _anchor(240, 540)
    v3 = _anchor(120, 560)
    v4 = _anchor(80, 480)
    poly = _track(
        Polygon(
            points=[lambda: v0, lambda: v1, lambda: v2, lambda: v3, lambda: v4],
        ).set_color("red")
    )

    _cap("Hub spokes → centers", 400, 640)
    hub = _anchor(700, 480)
    c1_c = _anchor(480, 560)
    c1 = _track(Circle(center=lambda: c1_c, radius=30).set_color("cyan"))
    c2_c = _anchor(560, 360)
    c2 = _track(Square(center=lambda: c2_c, length=50).set_color("gold"))
    c3_c = _anchor(780, 360)
    c3 = _track(Ellipse(center=lambda: c3_c, width=90, height=45).set_color("magenta"))
    c4_c = _anchor(860, 560)
    c4 = _track(RegularPolygon(n=5, center=lambda: c4_c, radius=35).set_color("lime"))
    for i, get_c in enumerate(
        (
            lambda: c1.center,
            lambda: c2.center,
            lambda: c3.center,
            lambda: c4.center,
            lambda: poly.centroid,
        )
    ):
        spoke = _track(
            Line(p1=lambda: hub, p2=get_c).set_color("indigo"),
            interact=False,
        )
        spoke.set_alpha(0.45)
        spoke.line_width = 1


def _apply():
    global _page_i
    _clear()
    name, expect, fn = PAGES[_page_i]
    hud.title = f"Shape catalog — [{_page_i + 1}/{len(PAGES)}] {name}"
    hud.expect = expect
    hud.status = f"handles={'on' if _show_handles else 'off'}  points={'on' if _show_points else 'off'}"
    fn()
    _enable_wheel()
    _apply_markers()


def setup(canvas):
    _apply()


def update(dt):
    global _page_i, _show_handles, _show_points, _show_colliders
    if not st.paused:
        dtheta = float(st.spin_speed) * dt
        st.spin = float(st.spin) + dtheta
        for shape, k in _spin:
            if getattr(shape, "is_alive", True):
                shape.rotate_by(k * dtheta)

    if keyp.once("A"):
        _page_i = (_page_i - 1) % len(PAGES)
        _apply()
    if keyp.once("S"):
        _page_i = (_page_i + 1) % len(PAGES)
        _apply()
    if keyp.once("SPACE"):
        st.paused = 0 if st.paused else 1
        hud.status = "paused" if st.paused else "running"
    if keyp.once("R"):
        st.spin_speed = 45.0
        st.spin = 0.0
        for shape, _k in _spin:
            if getattr(shape, "is_alive", True):
                try:
                    shape.rotate_to(0.0)
                except Exception:
                    pass
        hud.status = "spin reset"
    if keyp.once("H"):
        _show_handles = not _show_handles
        _apply_markers()
        hud.status = f"handles={'on' if _show_handles else 'off'}"
    if keyp.once("P"):
        _show_points = not _show_points
        _apply_markers()
        hud.status = f"points={'on' if _show_points else 'off'}"
    if keyp.once("C"):
        _show_colliders = not _show_colliders
        collision.show_colliders(_show_colliders)
        hud.status = f"outlines {'ON' if _show_colliders else 'OFF'}"


run()
