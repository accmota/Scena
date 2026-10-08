"""Spec A for tests/programs/geometry_lab.py, written from the docs alone.

Frozen before the engine ran. Every expectation cites the doc passage it rests
on; guess=True marks the ones the docs do not settle.
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close, serial)
import math

FILES_READ = [
    "tests/programs/geometry_lab.py",
    "tests/programs/spec_agent_prompt.txt",
    "docs/pt/guide/index.html#shape-point",
    "docs/pt/guide/index.html#geometria",
    "docs/pt/guide/index.html#geo-intersecoes",
    "docs/pt/guide/index.html#geo-helpers",
    "docs/pt/guide/index.html#ponto-like",
    "docs/pt/guide/index.html#util-remap",
    "docs/pt/guide/index.html#util-lerp",
    "docs/pt/guide/index.html#util-deadzone",
    "docs/pt/guide/index.html#history",
    "docs/pt/guide/index.html#contrail",
    "docs/pt/guide/index.html#frame-clock",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#frame-mouse",
    "docs/pt/guide/index.html#comecar-callbacks",
    "docs/pt/guide/index.html#reagir-callbacks",
    "docs/pt/guide/index.html#reativo",
    "docs/pt/guide/index.html#reativo-state",
    "docs/pt/guide/index.html#spr-hit",
    "docs/pt/guide/index.html#spr-hit-medir",
    "docs/pt/guide/index.html#spr-svg",
    "docs/pt/guide/index.html#shape-regular",
    "docs/pt/guide/index.html#shape-triangle",
    "docs/pt/guide/index.html#shape-square",
    "docs/pt/guide/index.html#grp-ler",
    "design/ (grep only: 'paus', 'hitbox')",
    "examples/media/k-textures (file listing only)",
]

# ---------------------------------------------------------------- constants
W, H = 1000, 700
CX, CY = 500.0, 350.0
DT = 1.0 / 60.0
A0 = (200.0, 560.0)
B0 = (520.0, 620.0)
D0 = math.hypot(320.0, 60.0)                       # 325.576...
HEAD0 = math.degrees(math.atan2(60.0, 320.0))      # 10.6197...
HEX_C = (670.0, 410.0)
HEX_R = 60.0
HEX_IN = 60.0 * math.cos(math.radians(30))         # inradius 51.96
ORBIT_STEP = 0.8 * DT * 230.0                      # max orbit move per frame (default speed)
SLIDER_STEP = 0.5 * 1.3 * DT * 160.0               # max slider x move per frame


def _v(x):
    """A State field reads as its cell (Attribute); .value is the plain value."""
    return getattr(x, "value", x)


def _wrap(a):
    return (a + 180.0) % 360.0 - 180.0


def _ell(pt):
    x, y = pt
    return ((x - CX) / 180.0) ** 2 + ((y - CY) / 100.0) ** 2 - 1.0


def _ell_angle(pt):
    x, y = pt
    return math.degrees(math.atan2((y - CY) / 100.0, (x - CX) / 180.0)) % 360.0


def _orbit(t, speed=0.8):
    return (CX + 230.0 * math.cos(t * speed), CY + 150.0 * math.sin(t * speed))


def _slider_at(t):
    w = (math.sin(t * 1.3) + 1.0) / 2.0
    return (200.0 + 160.0 * w, 310.0 + 80.0 * w)


def _d(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


# stateful probe: remembers the first pin of this run (keyed by the run's namespace)
_first = {"rec": None}


def _first_pin_alive(p):
    rec = _first["rec"]
    if rec is None or rec[0] is not p.pins:      # a new run has a new History
        _first["rec"] = None
        if len(p.pins) == 0:
            return -1.0
        rec = (p.pins, p.pins.first)
        _first["rec"] = rec
    return 1.0 if rec[1].is_alive else 0.0


# ---------------------------------------------------------------- probes
PROBES = {
    "time": lambda p: p.clock.time,
    "paused": lambda p: bool(p.clock.paused),
    "a": lambda p: p.a.center,
    "b": lambda p: p.b.center,
    "seg_p1": lambda p: p.segment.p1,
    "seg_p2": lambda p: p.segment.p2,
    "mid": lambda p: p.mid.center,
    "mid_r": lambda p: p.mid.radius,
    "quarter": lambda p: p.quarter.center,
    "dist": lambda p: _v(p.st.dist),
    "heading": lambda p: _v(p.st.heading),
    "hits": lambda p: _v(p.st.hits),
    "nearest": lambda p: _v(p.st.nearest),
    "st_pins": lambda p: _v(p.st.pins),
    "tri": lambda p: p.tri.center,
    "tri_angle": lambda p: p.tri.angle,
    "slider": lambda p: p.slider.center,
    "hexa_angle": lambda p: p.hexa.angle,
    "cross0": lambda p: p.cross0.center,
    "cross1": lambda p: p.cross1.center,
    "trail_len": lambda p: len(p.trail),
    "pins_len": lambda p: len(p.pins),
    "pins_serials": lambda p: tuple(serial(c) for c in p.pins),
    "pins_alive": lambda p: all(c.is_alive for c in p.pins),
    "last_pin": lambda p: p.pins.last.center if len(p.pins) else None,
    "first_pin_alive": _first_pin_alive,
    "follower": lambda p: p.follower.center,
    "target": lambda p: (p.target.x, p.target.y),
    "dot": lambda p: p.probe.center,
    "mouse": lambda p: (p.mouse.x, p.mouse.y),
    "hud": lambda p: p.hud.text,
    "caption": lambda p: p.caption.text,
    "badge_w": lambda p: _v(p.st.badge_hitbox_w),
    "oval_hitbox": lambda p: _v(p.st.oval_hitbox),
    "oval_fill_none": lambda p: p.oval.fill is None,
    "hexa_fill_none": lambda p: p.hexa.fill is None,
    "slider_textured": lambda p: isinstance(p.slider.fill, p.Texture),
    "shape_group": lambda p: tuple(p.name_of(s) for s in p.group["shape"]),
    "canvas_size": lambda p: (p.canvas.width, p.canvas.height),
}

# ---------------------------------------------------------------- scenarios
_pins7 = []
for _ in range(7):
    _pins7 += [key("SPACE"), wait(10)]
_pins4 = []
for _ in range(4):
    _pins4 += [key("SPACE"), wait(10)]

SCENARIOS = {
    "idle": Scenario(seed=0, steps=[wait(150)]),
    "right": Scenario(seed=0, steps=[wait(10), key("RIGHT", frames=60), wait(10)]),
    "left": Scenario(seed=0, steps=[wait(10), key("LEFT", frames=30), wait(10)]),
    "pins": Scenario(seed=0, steps=[wait(5)] + _pins7),
    "pins3": Scenario(params={"pins": 3}, seed=0, steps=[wait(5)] + _pins4),
    "pause": Scenario(seed=0, steps=[wait(100), key("P"), wait(60), key("P"), wait(30)]),
    "click": Scenario(seed=0, steps=[wait(5), click(850, 180), wait(5),
                                     click(700, 120), wait(20)]),
    "click_slack": Scenario(params={"slack": 400}, seed=0,
                            steps=[wait(5), click(700, 120), wait(20)]),
    "mouse": Scenario(params={"speed": 0}, seed=0, steps=[
        wait(3), move(190, 190), wait(5), move(50, 50), wait(5),
        move(660, 420), wait(5), move(730, 340), wait(5), move(920, 540), wait(5)]),
    "speed0": Scenario(params={"speed": 0}, seed=0, steps=[wait(60)]),
}

NOT_PAUSED = ("idle", "right", "left", "pins", "pins3", "click", "click_slack", "mouse", "speed0")
NO_RIGHT_LEFT = ("idle", "pins", "pins3", "pause", "click", "click_slack", "mouse", "speed0")


# ---------------------------------------------------------------- custom checks
def _time_is_frames(t):
    for s in t.samples:
        if abs(s.values["time"] - s.frame * DT) > 1e-6:
            return f"frame {s.frame}: clock.time {s.values['time']} != {s.frame}/60"
    return True


def _tri_orbit(tol, speed=0.8):
    def fn(t):
        for s in t.samples:
            exp = _orbit(s.values["time"], speed)
            if _d(s.values["tri"], exp) > tol:
                return f"frame {s.frame}: tri {s.values['tri']} vs orbit {exp}"
        return True
    return fn


def _slider_check(t):
    for s in t.samples:
        x, y = s.values["slider"]
        if not (200 - 1e-6 <= x <= 360 + 1e-6 and 310 - 1e-6 <= y <= 390 + 1e-6):
            return f"frame {s.frame}: slider {x, y} off its stops"
        if abs((y - 350.0) - 0.5 * (x - 280.0)) > 1e-4:
            return f"frame {s.frame}: slider {x, y} off the line between the stops"
        exp = _slider_at(s.values["time"])
        if _d((x, y), exp) > SLIDER_STEP + 0.05:
            return f"frame {s.frame}: slider {x, y} vs lerp at clock.time {exp}"
    return True


def _hexa_angle(t):
    for s in t.samples:
        exp = 25.0 * s.values["time"]
        if abs(_wrap(s.values["hexa_angle"] - exp)) > 1e-3:
            return f"frame {s.frame}: hexa.angle {s.values['hexa_angle']} != 25*time {exp}"
    return True


def _crossings_on_both(t):
    for s in t.samples:
        for k in ("cross0", "cross1"):
            pt = s.values[k]
            if abs(_ell(pt)) > 2e-3:
                return f"frame {s.frame}: {k} {pt} not on the ellipse"
            r = _d(pt, HEX_C)
            if not (HEX_IN - 0.05 <= r <= HEX_R + 0.05):
                return f"frame {s.frame}: {k} {pt} not on the hexagon ring (r={r})"
        if _d(s.values["cross0"], s.values["cross1"]) < 1.0:
            return f"frame {s.frame}: the two crossing markers coincide"
    return True


def _crossing_order(t):
    for s in t.samples:
        a0, a1 = _ell_angle(s.values["cross0"]), _ell_angle(s.values["cross1"])
        if s.values["hits"] == 2 and not a0 < a1:
            return f"frame {s.frame}: cross0 angle {a0} not before cross1 angle {a1}"
    return True


def _hud_matches(t):
    for s in t.samples:
        v = s.values
        exp = (f"d = {v['dist']:.1f}\nheading = {v['heading']:.1f}\n"
               f"crossings = {int(v['hits'])}\nnearest = {v['nearest']}\npins = {int(v['st_pins'])}")
        if v["hud"] != exp:
            return f"frame {s.frame}: hud {v['hud']!r} != {exp!r}"
    return True


def _caption_matches(t):
    prev_paused = None
    for s in t.samples:
        text = s.values["caption"]
        if not text.startswith("t = "):
            return f"frame {s.frame}: caption {text!r}"
        num = float(text[4:].split("s")[0])
        if abs(num - s.values["time"]) > DT + 0.006:
            return f"frame {s.frame}: caption time {num} vs clock.time {s.values['time']}"
        paused = s.values["paused"]
        if prev_paused is not None and paused == prev_paused:
            if ("(paused)" in text) != bool(paused):
                return f"frame {s.frame}: caption {text!r} vs paused={paused}"
        prev_paused = paused
    return True


def _b_after_key(lo, hi, name):
    def fn(t):
        rel = t.release_frame(name)
        bx = t.end("b")[0]
        if not (lo - 0.01 <= bx <= hi + 0.01):
            return f"b.x at end {bx} not in [{lo}, {hi}]"
        if abs(t.end("b")[1] - 620.0) > 1e-9:
            return "b.y changed"
        # after the release b no longer moves
        later = [v for f, _, v in t.series("b") if f > rel + 1]
        if later and any(abs(v[0] - later[0][0]) > 1e-9 for v in later):
            return "b kept moving after release"
        return True
    return fn


def _segment_follows(t):
    for s in t.samples:
        v = s.values
        if not close(v["seg_p1"], v["a"], 1e-6) or not close(v["seg_p2"], v["b"], 1e-6):
            return f"frame {s.frame}: segment ends {v['seg_p1']},{v['seg_p2']} vs anchors"
        m = ((v["a"][0] + v["b"][0]) / 2, (v["a"][1] + v["b"][1]) / 2)
        if not close(v["mid"], m, 1e-6):
            return f"frame {s.frame}: mid {v['mid']} != {m}"
        q = (v["a"][0] + 0.25 * (v["b"][0] - v["a"][0]), v["a"][1] + 0.25 * (v["b"][1] - v["a"][1]))
        if not close(v["quarter"], q, 1e-6):
            return f"frame {s.frame}: quarter {v['quarter']} != {q}"
    return True


def _readouts_follow(t):
    for s in t.samples:
        v = s.values
        d = _d(v["a"], v["b"])
        h = math.degrees(math.atan2(v["b"][1] - v["a"][1], v["b"][0] - v["a"][0]))
        if abs(v["dist"] - d) > 1e-6:
            return f"frame {s.frame}: st.dist {v['dist']} != {d}"
        if abs(v["heading"] - h) > 1e-6:
            return f"frame {s.frame}: st.heading {v['heading']} != {h}"
        if abs(v["mid_r"] - (4 + 10 * d / 800)) > 1e-6:
            return f"frame {s.frame}: mid.radius {v['mid_r']} != remap"
    return True


def _pins_counts(maxn, presses):
    def fn(t):
        for n in range(presses):
            f = t.press_frame("SPACE", n)
            got = t.at_frame(f, "pins_len")
            if got != min(n + 1, maxn):
                return f"after press {n + 1}: len(pins)={got}, expected {min(n + 1, maxn)}"
            if t.at_frame(f, "st_pins") != min(n + 1, maxn):
                return f"after press {n + 1}: st.pins={t.at_frame(f, 'st_pins')}"
        return True
    return fn


def _pin_at_triangle(t):
    n = 0
    while True:
        try:
            f = t.press_frame("SPACE", n)
        except Exception:
            break
        if f is None:
            break
        pin = t.at_frame(f, "last_pin")
        tri = t.at_frame(f, "tri")
        if pin is None or _d(pin, tri) > ORBIT_STEP + 0.1:
            return f"press {n + 1}: newest pin {pin} vs triangle {tri}"
        n += 1
    return True if n > 0 else "no SPACE press found"


def _oldest_leaves(t):
    f6 = t.press_frame("SPACE", 5)
    before = t.at_frame(f6 - 1, "pins_serials")
    after = t.at_frame(f6, "pins_serials")
    if before[0] in after:
        return f"oldest pin {before[0]} still in history after 6th press"
    if tuple(after[:-1]) != tuple(before[1:]):
        return f"history order {after} does not continue {before}"
    for f, _, alive in t.series("first_pin_alive"):
        if f < f6 and f >= t.press_frame("SPACE", 0) and alive != 1.0:
            return f"frame {f}: first pin dead before it was evicted"
        if f >= f6 and alive != 0.0:
            return f"frame {f}: first pin still alive after eviction"
    return True


def _pause_freezes(t):
    f0 = t.press_frame("P", 0)
    f1 = t.press_frame("P", 1)
    if not t.at_frame(f0, "paused") or t.at_frame(f1, "paused"):
        return "P did not toggle clock.paused"
    t0 = t.at_frame(f0, "time")
    for k in ("time", "tri", "hexa_angle", "slider"):
        ref = t.at_frame(f0, k)
        for f in range(f0 + 1, f1):
            if not close(t.at_frame(f, k), ref, 1e-9):
                return f"frame {f}: {k} moved while paused"
    # it runs again after resume
    if not t.end("time") > t0 + 0.2:
        return "clock did not advance after resuming"
    return True


def _trail_frozen_in_pause(t):
    f0 = t.press_frame("P", 0)
    f1 = t.press_frame("P", 1)
    ref = t.at_frame(f0 + 1, "trail_len")
    for f in range(f0 + 1, f1):
        if t.at_frame(f, "trail_len") != ref:
            return f"frame {f}: trail length changed while paused"
    return True


def _trail_bounds(t):
    for s in t.samples:
        n = s.values["trail_len"]
        if n > 31:
            return f"frame {s.frame}: trail has {n} > 31 points (1.5 s at 0.05 s)"
        if s.values["time"] >= 1.6 and not 29 <= n <= 31:
            return f"frame {s.frame}: trail has {n} points at steady state"
    return True


def _follower_click(t):
    r0 = t.release_frame("left", 0)
    r1 = t.release_frame("left", 1)
    for f in range(1, r1):
        if not close(t.at_frame(f, "follower"), (850.0, 150.0), 1e-6):
            return f"frame {f}: follower moved while the target was inside its slack"
    if not close(t.at_frame(r0 + 1, "target"), (850.0, 180.0), 1e-6):
        return f"target after first click {t.at_frame(r0 + 1, 'target')}"
    for f, _, v in t.series("follower"):
        if f >= r1 + 1 and not close(v, (760.0, 150.0), 1e-6):
            return f"frame {f}: follower {v} != (760, 150)"
    if not close(t.end("target"), (700.0, 120.0), 1e-6):
        return f"target at end {t.end('target')}"
    return True


def _mouse_reads(t):
    plan = [  # move index -> (nearest name, closest point on poly or None)
        (0, "poly", (190.0, 190.0)),
        (1, None, (90.0, 120.0)),
        (2, "hexagon", None),
        (3, "triangle", None),
        (4, "badge", None),
    ]
    for i, name, dot in plan:
        f = t.input_frame("move", i) + 1
        if name is not None and t.at_frame(f, "nearest") != name:
            return f"move {i}: nearest {t.at_frame(f, 'nearest')!r}, expected {name!r}"
        if dot is not None and not close(t.at_frame(f, "dot"), dot, 1e-3):
            return f"move {i}: dot {t.at_frame(f, 'dot')} expected {dot}"
    return True


# ---------------------------------------------------------------- expectations
G = "docs/pt/guide/index.html"
EXPECT = [
    # ---- startup / static facts
    Expect(id="E1", level="L0", cite=f"{G}#init",
           text="init(width=1000, height=700) sets the design space: canvas.width/height = 1000/700.",
           check=always("canvas_size", lambda v: close(v, (1000.0, 700.0), 1e-9)), scenarios=("idle",)),
    Expect(id="E2", level="L0", cite=f"{G}#grp-ler",
           text="group['shape'] holds poly, square, triangle, hexagon, badge, in entry order.",
           check=at(1, "shape_group", lambda v: tuple(v) == ("poly", "square", "triangle", "hexagon", "badge")),
           scenarios=("idle",)),
    Expect(id="E3", level="L0", cite=f"{G}#mat-tex",
           text="fill = None on the ellipse and hexagon reads back None; the square's fill is a Texture.",
           check=all_of(always("oval_fill_none", lambda v: bool(v)),
                        always("hexa_fill_none", lambda v: bool(v)),
                        always("slider_textured", lambda v: bool(v))), scenarios=("idle",)),
    Expect(id="E4", level="L1", cite=f"{G}#frame-clock",
           text="With fixed dt = 1/60 and no pause, clock.time after frame n is n/60 (the first dt counts from run()).",
           check=custom(_time_is_frames), scenarios=NOT_PAUSED),

    # ---- anchors, segment, middle point, readouts
    Expect(id="E5", level="L0", cite=f"{G}#shape-point",
           text="Without dragging, Anchor a stays at (200, 560) and b at (520, 620).",
           check=all_of(always("a", lambda v: close(v, A0, 1e-9)), always("b", lambda v: close(v, B0, 1e-9))),
           scenarios=NO_RIGHT_LEFT),
    Expect(id="E6", level="L1", cite=f"{G}#shape-point (Anchor: 'Ligar a um Anchor pede lambda')",
           text="Line(p1=lambda: a.center, p2=lambda: b.center) and the middle/quarter circles follow the anchors every frame (middle_point = weight 0.5, lerp t=0.25).",
           check=custom(_segment_follows), scenarios=("*",)),
    Expect(id="E7", level="L1", cite=f"{G}#geo-helpers",
           text="st.dist = distance(a, b), st.heading = heading(a, b) in degrees (0 = +x), mid.radius = remap(dist, 0, 800, 4, 14), all live.",
           check=custom(_readouts_follow), scenarios=("*",)),
    Expect(id="E8", level="L1", cite=f"{G}#geo-helpers; {G}#util-remap",
           text="At rest: dist = sqrt(320^2+60^2) = 325.576, heading = atan2(60, 320) = 10.620 deg, mid.radius = 8.0697.",
           check=all_of(always("dist", lambda v: abs(v - D0) < 1e-6),
                        always("heading", lambda v: abs(v - HEAD0) < 1e-6),
                        always("mid_r", lambda v: abs(v - (4 + 10 * D0 / 800)) < 1e-6)),
           scenarios=("idle", "pins", "click", "mouse")),
    Expect(id="E9", level="L1", cite=f"{G}#frame-teclado",
           text="Holding RIGHT for 60 frames moves b right by 150*dt per held frame: b.x ends in [670, 672.5] (60 or 61 frames of keyp), b.y unchanged, no motion after release.",
           check=custom(_b_after_key(670.0, 672.5, "RIGHT")), scenarios=("right",)),
    Expect(id="E10", level="L1", cite=f"{G}#frame-teclado",
           text="Holding LEFT for 30 frames moves b left by 150*dt per held frame: b.x ends in [442.5, 445].",
           check=custom(_b_after_key(442.5, 445.0, "LEFT")), scenarios=("left",)),
    Expect(id="E11", level="L1", cite=f"{G}#geo-helpers",
           text="After RIGHT, the heading drops below its rest value and the distance grows (b moved right along +x).",
           check=all_of(at_end("heading", lambda v: v < HEAD0 - 1.0),
                        at_end("dist", lambda v: v > D0 + 100.0)), scenarios=("right",)),

    # ---- movers
    Expect(id="E12", level="L1", cite=f"{G}#frame-clock (Em @=: clock.time in a lambda)",
           text="The triangle centre follows (CX + 230 cos(0.8 t), CY + 150 sin(0.8 t)) within one frame's step (3.07 units) of clock.time.",
           check=custom(_tri_orbit(ORBIT_STEP + 0.1)), scenarios=("idle", "pins", "pause", "click")),
    Expect(id="E13", level="L1", cite=f"{G}#frame-clock",
           text="Guess: the formula is current when read, so tri.center matches the orbit at the same sample's clock.time to 1e-3.",
           check=custom(_tri_orbit(1e-3)), scenarios=("idle",), guess=True),
    Expect(id="E14", level="L0", cite=f"{G}#shape-triangle",
           text="The program never turns the triangle: tri.angle stays 0 (the default apex direction).",
           check=always("tri_angle", lambda v: abs(_wrap(v)) < 1e-9), scenarios=("idle",)),
    Expect(id="E15", level="L1", cite=f"{G}#frame-clock",
           text="PARAMS speed=0 freezes the orbit at (CX + 230, CY) = (730, 350).",
           check=always("tri", lambda v: close(v, (730.0, 350.0), 1e-6)), scenarios=("speed0", "mouse")),
    Expect(id="E16", level="L1", cite=f"{G}#util-remap; {G}#util-lerp",
           text="The square sits on the segment (200,310)-(360,390) at lerp weight remap(sin(1.3 t), -1, 1, 0, 1), within one frame's step.",
           check=custom(_slider_check), scenarios=("idle", "pause")),
    Expect(id="E17", level="L1", cite=f"{G}#shape-regular; {G}#mover-pose",
           text="hexa.rotate_by(25*dt) each frame from angle 0: hexa.angle = 25 * clock.time (mod 360).",
           check=custom(_hexa_angle), scenarios=NOT_PAUSED),

    # ---- intersections
    Expect(id="E18", level="L2", cite=f"{G}#geo-intersecoes",
           text="The hexagon (circumradius 60 at (670,410)) always crosses the ellipse outline exactly twice for any rotation (checked by hand over 0-60 deg): st.hits == 2.",
           check=always("hits", lambda v: v == 2), scenarios=("idle", "pause")),
    Expect(id="E19", level="L2", cite=f"{G}#geo-intersecoes",
           text="intersection(oval, hexa, 0/1) markers lie on the ellipse (|f| < 2e-3) and on the hexagon ring (inradius..circumradius), and are distinct.",
           check=custom(_crossings_on_both), scenarios=("idle",)),
    Expect(id="E20", level="L0", cite=f"{G}#geo-intersecoes (Ordem)",
           text="Guess: with the Ellipse first, crossings are ordered along it from local +x counter-clockwise, so cross0's ellipse angle is below cross1's.",
           check=custom(_crossing_order), scenarios=("idle",), guess=True),

    # ---- mouse: closest_point and nearest
    Expect(id="E21", level="L1", cite=f"{G}#geo-helpers (Neste closest_point)",
           text="The probe dot is closest_point(poly, mouse): the mouse itself inside the polygon ((190,190)), the vertex (90,120) for a mouse at (50,50).",
           check=custom(_mouse_reads), scenarios=("mouse",)),
    Expect(id="E22", level="L0", cite=f"{G}#geo-helpers (Neste nearest)",
           text="st.nearest names the group['shape'] member whose centre is nearest the pointer (poly, hexagon, triangle, badge at the moved positions; speed=0).",
           check=custom(_mouse_reads), scenarios=("mouse",)),

    # ---- click + deadzone
    Expect(id="E23", level="L1", cite=f"{G}#util-deadzone; {G}#reagir-callbacks",
           text="on_mouse_click moves the target; the follower stays at (850,150) while the target is inside its 120 box, and moves to (760,150) once the target is (700,120) (back to the box edge, y inside the box).",
           check=custom(_follower_click), scenarios=("click",)),
    Expect(id="E24", level="L1", cite=f"{G}#util-deadzone",
           text="With slack=400 (half 200) a target at (700,120) stays inside the box: the follower never moves.",
           check=all_of(always("follower", lambda v: close(v, (850.0, 150.0), 1e-6)),
                        at_end("target", lambda v: close(v, (700.0, 120.0), 1e-6))),
           scenarios=("click_slack",)),
    Expect(id="E25", level="L0", cite=f"{G}#util-deadzone",
           text="With no click the follower and target never move.",
           check=all_of(always("follower", lambda v: close(v, (850.0, 150.0), 1e-6)),
                        always("target", lambda v: close(v, (850.0, 150.0), 1e-6))),
           scenarios=("idle", "mouse")),

    # ---- History of pins
    Expect(id="E26", level="L0", cite=f"{G}#history; {G}#reagir-callbacks",
           text="Each SPACE adds one pin; History(max_points=5) caps at 5, and st.pins mirrors len(pins) in the same frame.",
           check=custom(_pins_counts(5, 7)), scenarios=("pins",)),
    Expect(id="E27", level="L0", cite=f"{G}#history",
           text="PARAMS pins=3 caps the history at 3 after 4 presses.",
           check=custom(_pins_counts(3, 4)), scenarios=("pins3",)),
    Expect(id="E28", level="L0", cite=f"{G}#history (add / destroy_on_leave=True)",
           text="On the 6th press the oldest pin leaves the history (order kept) and, being an Entity, is destroyed; it was alive until then.",
           check=custom(_oldest_leaves), scenarios=("pins",)),
    Expect(id="E29", level="L0", cite=f"{G}#history",
           text="Every pin still in the history is alive.",
           check=always("pins_alive", lambda v: bool(v)), scenarios=("pins", "pins3")),
    Expect(id="E30", level="L1", cite=f"{G}#ponto-like ('copia a posição agora')",
           text="A pin is placed at the triangle's centre at the press (within one frame's orbit step) and does not follow it.",
           check=custom(_pin_at_triangle), scenarios=("pins",)),
    Expect(id="E31", level="L0", cite=f"{G}#history",
           text="No pins without SPACE.",
           check=always("pins_len", lambda v: v == 0), scenarios=("idle", "click", "mouse")),

    # ---- Contrail
    Expect(id="E32", level="L2", cite=f"{G}#contrail",
           text="tri.every(0.05) snapshots with duration=1.5 keep at most 31 points; from t >= 1.6 s the trail holds 29..31 (max_points 40 never binds).",
           check=custom(_trail_bounds), scenarios=("idle",)),

    # ---- pause
    Expect(id="E33", level="L0", cite=f"{G}#frame-clock",
           text="P toggles clock.paused; while paused clock.time, the orbit, the square and the hexagon angle stay frozen (dt = 0), and time advances again after the second P.",
           check=custom(_pause_freezes), scenarios=("pause",)),
    Expect(id="E34", level="L0", cite=f"{G}#contrail; design/Actors Design.md (Script-level after/every pause with the world)",
           text="Guess: the entity timer pauses and History duration counts game time, so the trail length is frozen while paused.",
           check=custom(_trail_frozen_in_pause), scenarios=("pause",), guess=True),

    # ---- text readouts
    Expect(id="E35", level="L0", cite=f"{G}#reativo; {G}#reativo-state",
           text="The HUD text (@= lambda over st fields) equals the formatted readouts every frame.",
           check=custom(_hud_matches), scenarios=("idle", "pins", "mouse", "right")),
    Expect(id="E36", level="L0", cite=f"{G}#frame-clock (Em @=)",
           text="The caption shows clock.time to 2 decimals (within one frame) and '(paused)' exactly while paused.",
           check=custom(_caption_matches), scenarios=("idle", "pause")),

    # ---- Svg / hitbox measures
    Expect(id="E37", level="L2", cite=f"{G}#spr-hit-medir; {G}#spr-svg",
           text="Guess: the Svg badge (a gold r=18 disk in a 40x40 drawing at height=40) measures a main hitbox box width between 32 and 38 ('auto' fits the disk, leaning inside).",
           check=always("badge_w", lambda v: 32.0 <= v <= 38.0), scenarios=("idle",), guess=True),
    Expect(id="E38", level="L0", cite=f"{G}#spr-hit (num Shape é a própria geometria)",
           text="Guess: an Ellipse's hitbox.shape reads 'ellipse' (the docs only say a Shape's hitbox is its own geometry).",
           check=at(1, "oval_hitbox", lambda v: v == "ellipse"), scenarios=("idle",), guess=True),
]
