"""
Smoke test for pointer hover (one per-frame target), @hover / @hover_exit,
and @click on Shapes, Sprites and Buttons.

Pages (A / S):

1. Cards      — @hover / @hover_exit on a group (Rects + a Sprite, alpha hit);
                labels on top never steal hover; one card lit at a time.
2. Ways out   — keep the mouse STILL on the circle; every key must drop or move
                the highlight on the next frame (hide, tween away, destroy,
                new target on top, move_to_front, clickable / handlers).
3. Still cursor — the accepted trade-off: a bar sliding under a parked cursor
                lights only when the mouse moves; it un-lights at once when it
                slides away. Arrows pan the camera: that counts as motion.
4. Hover-only — a planet with only @hover shows a tooltip but lets clicks
                through to the clickable rect below / to the script.
5. Widgets    — one @click handler for a Shape and a Button; Button fn() and
                fn(button); @hover on Button / Slider; a Button over a world
                shape takes hover; M opens a modal Menu (all hover off);
                CheckBox.on_click refuses.
6. ui layer   — a ui Graphic over a world one: ui wins; pan the camera.

The aux line counts edges: every enter must be followed by exactly one exit
("open" is 0 or 1, never more).
"""
from scena import *
import math
import sys as _sys
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _hud import SmokeHud, apply_camera

W, H = 1200, 900
init(width=W, height=H, window_scale=0.7, title="Smoke — Hover")
canvas.background = (0.08, 0.09, 0.12, 1)

hud = SmokeHud(title="Hover", expect="", keys="", status="move the mouse", show_aux=True)

IDLE = "dim gray"
LIT = "gold"

_PAGES: list = []
_owned: list = []
_page_i = 0
_edges: dict = {}   # id(target) -> [name, enters, exits]
_names: dict = {}   # id(target) -> display name
_script_clicks = 0
_p: dict = {}       # per-page handles


def _page(name: str, expect: str, keys: str):
    def deco(fn):
        _PAGES.append((name, expect, keys, fn))
        return fn
    return deco


def _track(obj):
    _owned.append(obj)
    return obj


def _cap(text: str, x: float, y: float, *, size: int = 14):
    return _track(Text(text, center=(x, y), layer="default", font_size=size,
                       color=Color(0.7, 0.75, 0.85, 1)))


def _named(obj, name: str):
    _names[id(obj)] = name
    return obj


def _name(target) -> str:
    return _names.get(id(target)) or getattr(target, "label", None) or type(target).__name__


def _note(msg: str) -> None:
    """What the last key did; shown on the aux line with the edge count."""
    _p["msg"] = msg


def _enter(target):
    rec = _edges.setdefault(id(target), [_name(target), 0, 0])
    rec[1] += 1
    hud.status = f"@hover      → {rec[0]}"


def _exit(target):
    rec = _edges.setdefault(id(target), [_name(target), 0, 0])
    rec[2] += 1
    hud.status = f"@hover_exit → {rec[0]}"


def _paint(shape):
    """Level: fill follows pointer_hover (independent of the edges)."""
    if shape.is_alive:
        shape.set_color(LIT if shape.pointer_hover else IDLE)


def _edge_line() -> str:
    enters = sum(r[1] for r in _edges.values())
    exits = sum(r[2] for r in _edges.values())
    bad = [r[0] for r in _edges.values() if r[1] - r[2] not in (0, 1)]
    ok = "OK" if not bad and enters - exits in (0, 1) else f"BUG: {bad}"
    return f"edges: {enters} enter / {exits} exit · open {enters - exits} · {ok}"


# --- 1. Cards ------------------------------------------------------------------

@_page(
    "Cards",
    "One card gold at a time (@hover / @hover_exit). Labels on top do not steal it. "
    "Sprite lights only on its drawn pixels.",
    "A/S page  ·  sweep the mouse across the cards and gaps",
)
def cards_page():
    cards = []
    for i in range(10):
        x = 170 + (i % 5) * 190
        y = 560 - (i // 5) * 190
        card = _track(Rect(center=(x, y), width=150, height=150, group="cards")
                      .set_color(IDLE))
        card.clickable = True
        _named(card, f"card {i}")
        _cap(f"card {i}", x, y, size=18)  # decorative: never a target
        cards.append(card)
    ship = _track(Sprite("../../examples/media/space/enemyGreen1.png", center=(600, 200),
                         size=110, group="cards"))
    _named(ship, "Sprite")
    _cap("Sprite (alpha)", 600, 120)

    @hover(group["cards"])
    def lit(card):
        _enter(card)
        if isinstance(card, Rect):
            card.set_color(LIT)
        else:
            card.scale = 1.25

    @hover_exit(group["cards"])
    def unlit(card):
        _exit(card)
        if isinstance(card, Rect):
            card.set_color(IDLE)
        else:
            card.scale = 1.0

    @click(group["cards"])
    def picked(card):
        hud.status = f"@click → {type(card).__name__}"


# --- 2. Ways out -----------------------------------------------------------------

@_page(
    "Ways out",
    "Park the mouse on the circle and keep it STILL. Each key must change the "
    "highlight on the next frame, without moving the mouse.",
    "A/S page  ·  H hide/show  ·  M tween away+back  ·  D destroy / R respawn  ·  "
    "T new target on top  ·  F front/back  ·  C clickable  ·  X hover handlers",
)
def ways_page():
    _cap("park the cursor here", 600, 250)
    _spawn_target()
    _p["top"] = None


def _spawn_target():
    t = _track(Circle(center=(600, 420), radius=120).set_color(IDLE))
    _named(t, "target")
    t.clickable = True
    t.on_hover = _enter
    t.on_hover_exit = _exit
    _p["target"] = t
    return t


def _ways_keys():
    t = _p.get("target")
    if keyp.once("R") and (t is None or not t.is_alive):
        _spawn_target()
        _note("respawned (lights when the pointer next moves or the set changed)")
        return
    if t is None or not t.is_alive:
        return
    if keyp.once("H"):
        t.visible = not t.visible
        _note(f"visible = {t.visible}  → expect {'exit' if not t.visible else 'enter'}")
    elif keyp.once("M"):
        t.move_to(600, 780, time=0.6, loops=2, yoyo=True)
        _note("tweening away: exit as it leaves; enter on return only after a mouse nudge")
    elif keyp.once("D"):
        t.destroy()
        _note("destroyed → exit fired at once (R respawns)")
    elif keyp.once("T"):
        top = _p.get("top")
        if top is not None and top.is_alive:
            top.destroy()
            _p["top"] = None
            _note("top target removed → circle takes hover back")
        else:
            top = _track(Rect(center=(600, 420), width=150, height=110).set_color("teal"))
            _named(top, "top rect")
            top.clickable = True
            top.on_hover = _enter
            top.on_hover_exit = _exit
            _p["top"] = top
            _note("new clickable on top → it takes hover (circle exits)")
    elif keyp.once("F"):
        top = _p.get("top")
        if top is None or not top.is_alive:
            _note("press T first (needs a second target)")
        elif _p.get("front") == "circle":
            t.move_to_back()
            _p["front"] = "rect"
            _note("circle to back → rect hovered")
        else:
            t.move_to_front()
            _p["front"] = "circle"
            _note("circle to front → circle hovered")
    elif keyp.once("C"):
        t.clickable = not t.clickable
        has = t.on_hover is not None
        _note(f"clickable = {t.clickable}; hover handlers {'on' if has else 'off'} → "
              + ("target (clickable)" if t.clickable
                 else "still hovered: hover handlers keep it a target" if has
                 else "not a target: pointer_hover drops"))
    elif keyp.once("X"):
        if t.on_hover is None:
            t.on_hover, t.on_hover_exit = _enter, _exit
        else:
            t.on_hover = t.on_hover_exit = None
        has = t.on_hover is not None
        _note(f"hover handlers {'on' if has else 'off'}; clickable = {t.clickable} → "
              + ("target" if has or t.clickable else "not a target: pointer_hover drops"))


# --- 3. Still cursor -----------------------------------------------------------------

@_page(
    "Still cursor",
    "Park the mouse on the crosshair. The sliding bar lights only after you nudge the "
    "mouse (accepted trade-off); it un-lights at once when it slides away.",
    "A/S page  ·  SPACE pause bar  ·  arrows pan camera (counts as motion)  ·  R reset view",
)
def still_page():
    bar = _track(Rect(center=(600, 420), width=70, height=260).set_color(IDLE))
    _named(bar, "bar")
    bar.clickable = True
    bar.on_hover = _enter
    bar.on_hover_exit = _exit
    _p["bar"] = bar
    _p["paused"] = False
    _p["t"] = 0.0
    _track(Line(p1=(580, 420), p2=(620, 420)).set_color("white"))
    _track(Line(p1=(600, 400), p2=(600, 440)).set_color("white"))
    _cap("crosshair", 600, 250)


def _still_update(dt):
    if keyp.once("SPACE"):
        _p["paused"] = not _p["paused"]
    if keyp.once("R"):
        canvas.reset_view()
    apply_camera(dt)
    bar = _p.get("bar")
    if bar is None or not bar.is_alive:
        return
    if not _p["paused"]:
        _p["t"] += dt
        bar.move_to(600 + 330 * math.sin(_p["t"] * 0.8), 420)
    _paint(bar)
    hud.aux = f"bar.pointer_hover = {bar.pointer_hover}   ·   " + _edge_line()


# --- 4. Hover-only ------------------------------------------------------------------

@_page(
    "Hover-only",
    "The planet has only @hover: it shows a tooltip, but a click on it goes to the "
    "rect below; a click on empty space goes to the script.",
    "A/S page  ·  hover the planet  ·  click planet / rect / empty space",
)
def hover_only_page():
    rect = _track(Rect(center=(600, 420), width=520, height=300).set_color("steel blue"))
    _named(rect, "rect")
    _p["rect_clicks"] = 0

    @click(rect)
    def rect_clicked(r):
        _p["rect_clicks"] += 1

    planet = _track(Circle(center=(600, 420), radius=90).set_color("coral"))
    _named(planet, "planet")
    tip = _track(Text("tooltip: planet (hover-only)", center=(600, 560), layer="default",
                      font_size=18, color="white"))
    tip.visible = False

    @hover(planet)
    def show_tip(p):
        _enter(p)
        tip.visible = True

    @hover_exit(planet)
    def hide_tip(p):
        _exit(p)
        tip.visible = False

    _p["planet"] = planet
    _cap("rect is clickable; planet is not", 600, 240)


# --- 5. Widgets -----------------------------------------------------------------------

@_page(
    "Widgets",
    "Reset + the world square share one @click. Hovering a widget turns world hover off. "
    "M opens a modal Menu: every hover must drop until you choose.",
    "A/S page  ·  click Reset / square / Beep  ·  hover Slider  ·  M modal menu",
)
def widgets_page():
    ui.stack_origin(40, 700)
    reset = _track(Button(label="Reset", width=200))
    beep = _track(Button(label="Beep (fn())", width=200,
                         on_click=lambda: setattr(hud, "status", "Beep: fn() called")))
    st.hover_vol = 0.5
    slider = _track(Slider(st.hover_vol, label="Vol"))
    square = _track(Rect(center=(700, 420), width=200, height=200).set_color(IDLE))
    _named(square, "square")
    # A world shape exactly under the Reset button: the button must win hover.
    under = _track(Rect(center=reset.box.center, width=260, height=90).set_color(IDLE))
    _named(under, "under Reset")
    under.clickable = True
    _p["square"] = square
    _p["under"] = under

    @click(reset, square)
    def pressed(target):
        hud.status = f"one handler, @click → {type(target).__name__}"

    @hover(reset, beep, slider, square)
    def w_enter(target):
        _enter(target)

    @hover_exit(reset, beep, slider, square)
    def w_exit(target):
        _exit(target)

    box = _track(CheckBox(label="no on_click"))
    try:
        box.on_click = lambda: None
        _p["refusal"] = "BUG: CheckBox.on_click was accepted"
    except TypeError as err:
        _p["refusal"] = str(err)
    _cap("square: @click shared with Reset", 700, 290)
    _cap("gray bar under Reset: world shape, must stay gray while Reset is hovered",
         600, 580, size=13)


def _widgets_update():
    for key in ("square", "under"):
        s = _p.get(key)
        if s is not None and s.is_alive:
            _paint(s)
    if keyp.once("M"):
        Menu(options=["OK"], title="Modal: all hover off",
             on_choose=lambda _o: setattr(hud, "status", "modal closed"))
    refusal = _p.get("refusal", "")
    hud.aux = _edge_line() + (f"   ·   CheckBox.on_click: {refusal[:60]}…" if refusal else "")


# --- 6. ui layer ---------------------------------------------------------------------------

@_page(
    "ui layer",
    "The ui disc (view space) sits over the world disc: only the ui one lights. "
    "Pan the camera: the world disc slides under it; hover follows without moving the mouse.",
    "A/S page  ·  arrows pan camera  ·  R reset view",
)
def ui_page():
    world = _track(Circle(center=(600, 420), radius=140).set_color(IDLE))
    _named(world, "world disc")
    world.clickable = True
    world.on_hover, world.on_hover_exit = _enter, _exit
    top = _track(Circle(center=(600, 420), radius=60, layer="ui").set_color(IDLE))
    _named(top, "ui disc")
    top.clickable = True
    top.on_hover, top.on_hover_exit = _enter, _exit
    _p["world"] = world
    _p["ui"] = top


def _ui_update(dt):
    if keyp.once("R"):
        canvas.reset_view()
    apply_camera(dt)
    for key in ("world", "ui"):
        s = _p.get(key)
        if s is not None and s.is_alive:
            _paint(s)


# --- paging ----------------------------------------------------------------------------------

def _clear():
    for o in reversed(list(_owned)):
        try:
            if getattr(o, "is_alive", True):
                o.destroy()
        except Exception:
            pass
    _owned.clear()
    _p.clear()
    _edges.clear()
    _names.clear()
    canvas.reset_view()
    ui.stack_reset()


def _rebuild():
    _clear()
    name, expect, keys, fn = _PAGES[_page_i]
    hud.title = f"Hover — {name}  ({_page_i + 1}/{len(_PAGES)})"
    hud.expect = expect
    hud.keys = keys
    hud.status = "move the mouse"
    hud.aux = ""
    fn()


def on_mouse_click(x, y, button):
    global _script_clicks
    _script_clicks += 1


def setup(_canvas):
    _rebuild()


def update(dt):
    global _page_i
    if keyp.once("A"):
        _page_i = (_page_i - 1) % len(_PAGES)
        _rebuild()
        return
    if keyp.once("S"):
        _page_i = (_page_i + 1) % len(_PAGES)
        _rebuild()
        return
    name = _PAGES[_page_i][0]
    if name == "Cards":
        hud.aux = _edge_line()
    elif name == "Ways out":
        _ways_keys()
        t = _p.get("target")
        if t is not None and t.is_alive:
            _paint(t)
        msg = _p.get("msg", "")
        hud.aux = (msg + "   ·   " if msg else "") + _edge_line()
    elif name == "Still cursor":
        _still_update(dt)
    elif name == "Hover-only":
        hud.aux = (f"rect clicks: {_p.get('rect_clicks', 0)}   ·   script clicks: "
                   f"{_script_clicks}   ·   " + _edge_line())
    elif name == "Widgets":
        _widgets_update()
    elif name == "ui layer":
        _ui_update(dt)
        hud.aux = _edge_line()


run()
