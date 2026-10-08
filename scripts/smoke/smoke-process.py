"""
process.py — smoke: scheduler, modes, async, Entity, active park, clock scale.

Labeled vignettes (not a game). Number keys focus a vignette; watch the status
board and moving tokens.

Vignettes
---------
  1  scene @every / named replace
  2  after + then= hop
  3  tween / move_to timed
  4  function modes + @exit_mode
  5  async dive (await wait / until)
  6  @when / @on_change
  7  active park (timers + collision freeze)
  8  clock.paused / clock.scale / entity time_scale
  9  on_destroy + destroy() inert ink
  0  author error is loud: enters an async mode that raises NameError.
     The window closes and the terminal traceback points at the author
     line (``missing_name.foo()``). Press it last.

Keys
----
  1–9 / 0   focus vignette (highlight + nudge)
  SPACE     pause / resume world clock
  Q / W     clock.scale − / +
  P         toggle active on park token
  R         reset park token + clock scale

Usage
-----
    python scripts/smoke/smoke-process.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — process")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="Process / scheduler",
    expect="Number keys focus a vignette — timers, modes, async, author errors",
    keys="1–9/0 vignette  ·  0=author errors (re-press re-fires via goto_mode)  ·  SPACE pause  ·  Q/W scale  ·  P park  ·  R reset",
    status="ready",
    show_aux=True,
    aux="clock …",
)

# ---------------------------------------------------------------------------
# Layout helpers — below HUD band (~TOP_BAND 130)
# ---------------------------------------------------------------------------
_COLS = (
    (120, 580), (400, 580), (680, 580), (960, 580), (1240, 580),
    (120, 280), (400, 280), (680, 280), (960, 280), (1240, 280),
)
_labels = {}


def _caption(i, text):
    x, y = _COLS[i]
    Text(
        text=text,
        top_left=(x - 70, y + 70),
        font_size=13,
        color=Color(0.7, 0.75, 0.85, 1),
    )


# ---------------------------------------------------------------------------
# 1 — scene @every / named replace
# ---------------------------------------------------------------------------
_caption(0, "1  @every named")
pulse = Circle(center=_COLS[0], radius=28).set_color("cyan")
_pulse_n = {"n": 0}


@every(0.55, name="pulse")
def _pulse_tick():
    _pulse_n["n"] += 1
    pulse.radius = 22 + 10 * ((_pulse_n["n"] % 2))
    if _focus == 1:
        hud.status = f"every pulse #{_pulse_n['n']}"


# ---------------------------------------------------------------------------
# 2 — after + then=
# ---------------------------------------------------------------------------
_caption(1, "2  after → then=")
hop = Circle(center=_COLS[1], radius=26).set_color("gold")


@on_mode
def hopping(e):
    e.set_color("orange")
    e.move_to(_COLS[1][0] + 40, _COLS[1][1] + 30, time=0.35, then=hopped)


@on_mode
def hopped(e):
    e.set_color("lime")
    if _focus == 2:
        hud.status = "after→then= arrived"


def _arm_hop():
    hop.mode = None
    hop.center = Point(*_COLS[1])
    hop.set_color("gold")
    hop.after(0.4, then=hopping)


# ---------------------------------------------------------------------------
# 3 — tween / move_to
# ---------------------------------------------------------------------------
_caption(2, "3  move_to timed")
tween_tok = Rect(center=_COLS[2], width=50, height=36).set_color("magenta")


def _arm_tween():
    tween_tok.center = Point(*_COLS[2])
    tween_tok.move_to(_COLS[2][0] + 60, _COLS[2][1] - 50, time=0.8, ease="ease_out")
    if _focus == 3:
        hud.status = "move_to running"


# ---------------------------------------------------------------------------
# 4 — function modes + exit
# ---------------------------------------------------------------------------
_caption(3, "4  mode + exit")
mode_tok = Square(center=_COLS[3], length=44).set_color("tomato")
_exit_hits = {"n": 0}


@on_mode
def glowing(e):
    e.set_color("white")
    e.every(0.25, lambda: e.rotate_by(25), name="spin")


@exit_mode(glowing)
def _leave_glow(e):
    _exit_hits["n"] += 1
    e.set_color("tomato")
    if _focus == 4:
        hud.status = f"exit_mode fired ({_exit_hits['n']})"


# ---------------------------------------------------------------------------
# 5 — async dive
# ---------------------------------------------------------------------------
_caption(4, "5  async dive")
diver = Circle(center=_COLS[4], radius=24).set_color("deep sky blue")


@on_mode
async def diving(e):
    e.set_color("orange")
    await wait(0.25)
    e.move_to(_COLS[4][0], _COLS[4][1] - 80, time=0.4)
    await wait(0.45)
    e.move_to(*_COLS[4], time=0.4)
    await wait(0.45)
    e.set_color("deep sky blue")
    e.mode = None
    if _focus == 5:
        hud.status = "async dive done"


# ---------------------------------------------------------------------------
# 6 — @when / @on_change
# ---------------------------------------------------------------------------
_caption(5, "6  @when / @on_change")
st.create("heat", initial=0.0)
Slider(st.heat, label="heat", width=200, min_value=0.0, max_value=100.0, show_value=True, top_left=(20, 228))
when_tok = Circle(center=_COLS[5], radius=30).set_color("gray")


@when(lambda: float(st.heat) >= 70.0)
def _hot():
    when_tok.set_color("red")
    if _focus == 6:
        hud.status = "when: heat ≥ 70"


@when(lambda: float(st.heat) < 70.0)
def _cool():
    when_tok.set_color("gray")


@on_change(st.heat)
def _heat_changed(v):
    if _focus == 6:
        hud.status = f"on_change heat={float(v):.0f}"


# ---------------------------------------------------------------------------
# 7 — active park
# ---------------------------------------------------------------------------
_caption(6, "7  active park")
park = Circle(center=_COLS[6], radius=28, group="park").set_color("lime")
probe = Circle(center=(_COLS[6][0] + 70, _COLS[6][1]), radius=18).set_color("white")
probe.draggable = True


@every(0.4, name="park_spin")
def _park_spin():
    if park.active:
        park.rotate_by(18)


@collide(park, probe)
def _park_hit(a, b, info):
    if _focus == 7:
        hud.status = "park collision (should not fire when parked)"
    park.set_color("yellow")


# ---------------------------------------------------------------------------
# 8 — clock scale
# ---------------------------------------------------------------------------
_caption(7, "8  clock scale")
scale_tok = Ellipse(center=_COLS[7], width=70, height=40).set_color("orchid")


@every(0.3, name="scale_spin")
def _scale_spin():
    scale_tok.rotate_by(20)


# ---------------------------------------------------------------------------
# 9 — destroy / on_destroy
# ---------------------------------------------------------------------------
_caption(8, "9  destroy")
_spawn_pt = _COLS[8]


def _spawn_victim():
    v = Circle(center=_spawn_pt, radius=26).set_color("coral")
    v.hp = 1

    def _gone(e):
        if _focus == 9:
            hud.status = "on_destroy fired"

    v.on_destroy = _gone
    return v


victim = _spawn_victim()


# ---------------------------------------------------------------------------
# 0 — author error is loud (raises; run() cleans up and exits)
# ---------------------------------------------------------------------------
_caption(9, "0  author error")
_err_origin = _COLS[9]

async_boom = Circle(center=_err_origin, radius=16).set_color("orchid")


@on_mode
async def boom_dive(e):
    e.set_color("orange")
    missing_name.foo()  # NameError: propagates out of run() with this line
    await wait(0.2)


# ---------------------------------------------------------------------------
# Focus / controls
# ---------------------------------------------------------------------------
_focus = 1
_vignette_names = {
    1: "1 @every",
    2: "2 after→then=",
    3: "3 move_to",
    4: "4 mode+exit",
    5: "5 async",
    6: "6 @when",
    7: "7 active park",
    8: "8 clock scale",
    9: "9 destroy",
    0: "0 author error",
}


def _set_focus(n: int):
    global _focus, victim
    _focus = n
    name = _vignette_names.get(n, str(n))
    hud.title = f"Process — {name}"
    hud.status = f"focus {name}"
    if n == 2:
        _arm_hop()
    elif n == 3:
        _arm_tween()
    elif n == 4:
        if mode_tok.mode == glowing:
            mode_tok.mode = None
        else:
            mode_tok.mode = glowing
    elif n == 5:
        diver.mode = diving
    elif n == 0:
        async_boom.goto_mode(boom_dive)  # raises NameError → window closes
    elif n == 9:
        if victim is None or not getattr(victim, "is_alive", True):
            victim = _spawn_victim()
        else:
            victim.destroy()
            victim = None
            hud.status = "destroyed (ink should be inert)"


def on_key_down(key):
    if key in "1234567890":
        _set_focus(int(key))
    elif key == "P":
        park.active = not park.active
        hud.status = f"park.active = {park.active}"
        if not park.active:
            park.set_color("gray")
        else:
            park.set_color("lime")
    elif key == "R":
        park.active = True
        park.set_color("lime")
        clock.scale = 1.0
        clock.paused = False
        hud.status = "reset park + clock"


def update(dt):
    paused = "paused" if clock.paused else "run"
    hud.aux = f"clock t={float(clock.time):.2f}  scale={float(clock.scale):.2f}  {paused}"
    if keyp.once("SPACE"):
        clock.paused = not clock.paused
        hud.status = f"clock.paused = {clock.paused}"
    if keyp("Q"):
        clock.scale = max(0.1, float(clock.scale) - 0.5 * dt)
        if _focus == 8:
            hud.status = f"clock.scale = {clock.scale:.2f}"
    if keyp("W"):
        clock.scale = min(4.0, float(clock.scale) + 0.5 * dt)
        if _focus == 8:
            hud.status = f"clock.scale = {clock.scale:.2f}"


_set_focus(1)
run()
