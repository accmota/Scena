"""Spec A for tests/programs/toybox.py, written from the docs only.

Drags (press -> move -> release) cannot be expressed with the step builders:
click(x, y) is a press frame + release frame at one point, and move(x, y) only
moves the pointer with no button held. So @drag_over / @drag_to / @drop_by are
tested only negatively (a press + release without motion fires none of them).
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close, serial)
import math

FILES_READ = [
    "tests/programs/spec_agent_prompt.txt",
    "tests/programs/toybox.py",
    "design/Scena Design.md#frame-order",
    "design/Scena Design.md#collision",
    "design/Shapes Design.md#pointer-interaction-click--drag--drop",
    "design/Shapes Design.md#drag-and-drop",
    "design/Shapes Design.md#hover-pointer_hover-hover--hover_exit",
    "docs/pt/guide/index.html#reagir-pointer",
    "docs/pt/guide/index.html#reagir-when",
    "docs/pt/guide/index.html#reagir-on-change",
    "docs/pt/guide/index.html#colisao-collide",
    "docs/pt/guide/index.html#colisao-resolve",
    "docs/pt/guide/index.html#colisao-touching",
    "docs/pt/guide/index.html#colisao-corpo (Consultas, Collider)",
    "docs/pt/guide/index.html#mundo-camadas (above / below)",
    "docs/pt/guide/index.html#mundo-grupos",
]

# ---------------------------------------------------------------- geometry
R_TOY = 22.0
INNER = (20.0, 980.0, 20.0, 680.0)          # inner faces of the four walls
GLUE = (20.0, 980.0, 310.0, 350.0)          # x0, x1, y0, y1
PAD_C, PAD_R = (220.0, 500.0), 60.0
POST = (485.0, 515.0, 430.0, 510.0)
CAP_C, CAP_R = (500.0, 520.0), 26.0
SCANNER = (850.0, 970.0, 605.0, 675.0)
SCAN_PT = (910.0, 640.0)
LAYERS_LINE = "layers -1/1"


def d_rect(x, y, r):
    x0, x1, y0, y1 = r
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return math.hypot(dx, dy)


def d_bumper(x, y):
    return min(d_rect(x, y, POST), math.hypot(x - CAP_C[0], y - CAP_C[1]) - CAP_R)


def d_pad(x, y):
    return math.hypot(x - PAD_C[0], y - PAD_C[1]) - PAD_R


def d_walls(x, y):
    return min(x - INNER[0], INNER[1] - x, y - INNER[2], INNER[3] - y)


# toy tuple layout
SID, X, Y, VX, VY, LOOSE, PH, RAD, MASS = range(9)


def toys(s):
    v = s.values["toys"]
    if not isinstance(v, tuple):
        raise ValueError(f"toys probe failed at frame {s.frame}: {v!r}")
    return v


def by_sid(s):
    return {int(e[SID]): e for e in toys(s)}


def pairs(samples):
    for a, b in zip(samples, samples[1:]):
        if b.frame == a.frame + 1:
            yield a, b


def frames_of(t, kind, fn=None):
    out, k = [], 0
    while k < 2000:
        try:
            f = fn(kind, k) if fn else t.input_frame(kind, k)
        except Exception:
            break
        if f is None:
            break
        out.append(f)
        k += 1
    return out


def ke(s):
    return sum(e[VX] ** 2 + e[VY] ** 2 for e in toys(s))


def sv(s, name):
    return s.values[name]


def under_pointer(s, lo=R_TOY - 0.5, hi=R_TOY + 0.5):
    mx, my = s.values["mouse"]
    tt = toys(s)
    strict = [i for i, e in enumerate(tt) if math.hypot(e[X] - mx, e[Y] - my) < lo]
    loose = [i for i, e in enumerate(tt) if math.hypot(e[X] - mx, e[Y] - my) <= hi]
    return strict, loose


def hovered_flags(s):
    return [i for i, e in enumerate(toys(s)) if e[PH]]


# ---------------------------------------------------------------- probes
def _st(name):
    return lambda p: getattr(p.st, name)


PROBES = {
    "toys": lambda p: tuple((serial(t), t.center.x, t.center.y, t.vel.x, t.vel.y,
                             bool(t.tagged("loose")), bool(t.pointer_hover),
                             t.radius, t.mass) for t in p.group["toy"]),
    "n_loose": lambda p: sum(1 for _ in p.group["loose"]),
    "wall_mass": lambda p: tuple(w.mass for w in p.group["wall"]),
    "resolve_enabled": lambda p: bool(p.collision.resolve_enabled),
    "mouse": lambda p: (p.mouse.x, p.mouse.y),
    "ring": lambda p: (bool(p.ring.visible), p.ring.center.x, p.ring.center.y),
    "layers": lambda p: (p.red_bin.layer, p.blue_bin.layer, p.glue.layer,
                         p.pad.layer, p.ring.layer),
    "bumper_n": lambda p: len(p.bumper.shapes),
    "text": lambda p: str(p.status.text),
}
for _n in ("count", "speed", "binned", "changes", "flushed", "watching", "hovers",
           "hover_exits", "hovered", "over_frames", "over_target", "drops", "misses",
           "bumps", "bump_point", "pad_frames", "pad_exits", "glue_frames",
           "glue_exits", "wall_side", "scanned", "solid", "in_red", "in_blue"):
    PROBES[_n] = _st(_n)

# ---------------------------------------------------------------- scenarios
_GRID = [(x, y) for y in (420, 470, 520, 570)
         for x in (100, 200, 300, 400, 500, 600, 700, 800, 900)]
_hover_steps = [wait(60)]
for _x, _y in _GRID:
    _hover_steps += [move(_x, _y), wait(4)]
_hover_steps += [move(500, 250), wait(4),
                 click(150, 450), wait(3), click(650, 500), wait(3),
                 click(850, 560), wait(3), move(300, 470), wait(4)]

_scan_steps = [wait(30), move(*SCAN_PT)]
for _ in range(12):
    _scan_steps += [click(*SCAN_PT), wait(25)]

SCENARIOS = {
    # nothing pressed, default PARAMS (count 6, speed 160)
    "idle": Scenario(params={}, seed=0, steps=[wait(480)]),
    # still toys; one scanner click
    "still": Scenario(params={"speed": 0}, seed=1,
                      steps=[wait(60), move(*SCAN_PT), click(*SCAN_PT), wait(60)]),
    # still, dense toys; pointer sweeps a grid; clicks (press+release, no drag) on toys
    "hover": Scenario(params={"speed": 0, "count": 20}, seed=2, steps=_hover_steps),
    # many moving toys, repeated scanner clicks
    "scan": Scenario(params={"count": 20, "speed": 200}, seed=3, steps=_scan_steps),
    # R: ghost then solid again
    "ghost": Scenario(params={"count": 8}, seed=4,
                      steps=[wait(20), key("R"), wait(200), key("R"), wait(120)]),
    # P: all resolution off then on
    "pause": Scenario(params={"count": 4, "speed": 120}, seed=5,
                      steps=[wait(20), key("P"), wait(100), key("P"), wait(30)]),
    # cells, SPACE and U
    "cells": Scenario(params={}, seed=6, steps=[
        wait(10), set_cell("st.binned", 3), wait(5), set_cell("st.binned", 3), wait(5),
        key("SPACE"), wait(5), key("U"), wait(3), set_cell("st.binned", 7), wait(5),
        key("U"), wait(5)]),
}
ALL = tuple(SCENARIOS)
FEW_TOYS = ("idle", "still", "ghost", "pause", "cells")


def _start(t):
    """First frame the spawn overlaps are assumed resolved (dense scenarios wait longer)."""
    n = len(toys(t.samples[0]))
    return 60 if n >= 15 else 10


# ---------------------------------------------------------------- custom checks
def c_startup_counts(t):
    s = t.samples[0]
    n = int(sv(s, "count"))
    if len(toys(s)) != n:
        return f"{len(toys(s))} toys, st.count {n}"
    if int(sv(s, "n_loose")) != n:
        return f"{sv(s, 'n_loose')} loose toys, expected {n}"
    return None


def c_defaults(t):
    s = t.samples[0]
    if int(sv(s, "count")) != 6 or float(sv(s, "speed")) != 160.0:
        return f"defaults count={sv(s, 'count')} speed={sv(s, 'speed')}"
    if len(toys(s)) != 6:
        return f"{len(toys(s))} toys"
    return None


def c_walls(t):
    for s in t.samples:
        m = sv(s, "wall_mass")
        if len(m) != 4 or any(not math.isinf(x) for x in m):
            return f"frame {s.frame}: wall masses {m}"
    return None


def c_toy_body(t):
    for s in t.samples:
        for e in toys(s):
            if not close(e[RAD], 22.0, 1e-9) or not close(e[MASS], 1.0, 1e-9):
                return f"frame {s.frame}: toy radius {e[RAD]} mass {e[MASS]}"
    return None


def c_spawn_region(t):
    s = t.samples[0]
    slop = 28.0
    for e in toys(s):
        if not (80 - slop <= e[X] <= 920 + slop and 400 - slop <= e[Y] <= 580 + slop):
            return f"toy at ({e[X]:.1f}, {e[Y]:.1f}) outside the spawn box + {slop}"
    return None


def c_initial_state(t):
    s = t.samples[0]
    want = {"binned": 0, "changes": 0, "drops": 0, "misses": 0, "scanned": 0,
            "over_frames": 0}
    for k, v in want.items():
        if float(sv(s, k)) != v:
            return f"st.{k} = {sv(s, k)} at frame 1"
    for k in ("flushed", "watching", "solid", "resolve_enabled"):
        if not sv(s, k):
            return f"{k} false at frame 1"
    return None


def c_no_drag(t):
    for s in t.samples:
        if float(sv(s, "drops")) or float(sv(s, "misses")) or float(sv(s, "over_frames")):
            return (f"frame {s.frame}: drag callback ran (drops {sv(s, 'drops')}, "
                    f"misses {sv(s, 'misses')}, over {sv(s, 'over_frames')})")
        vis, rx, ry = sv(s, "ring")
        if vis or not close((rx, ry), (-100.0, -100.0), 1e-9):
            return f"frame {s.frame}: ring {sv(s, 'ring')}"
    return None


def c_bins_untouched(t):
    for s in t.samples:
        if not sv(s, "flushed"):
            return f"frame {s.frame}: st.flushed False"
        if float(sv(s, "in_red")) or float(sv(s, "in_blue")):
            return f"frame {s.frame}: in_red/in_blue nonzero"
        if int(sv(s, "n_loose")) != len(toys(s)):
            return f"frame {s.frame}: {sv(s, 'n_loose')} loose of {len(toys(s))}"
        if any(not e[LOOSE] for e in toys(s)):
            return f"frame {s.frame}: a toy lost its loose tag"
    return None


def c_text(t):
    for s in t.samples:
        v = s.values
        want = (f"bins {int(v['binned'])}  red {int(v['in_red'])}  blue {int(v['in_blue'])}  "
                f"drops {int(v['drops'])}  misses {int(v['misses'])}  "
                f"bumps {int(v['bumps'])}  scanned {int(v['scanned'])}  "
                f"{'solid' if v['solid'] else 'ghost'}  {LAYERS_LINE}")
        if v["text"] != want:
            return f"frame {s.frame}: text {v['text']!r} != {want!r}"
    return None


def c_hover_balance(t):
    for s in t.samples:
        d = float(sv(s, "hovers")) - float(sv(s, "hover_exits"))
        if d not in (0.0, 1.0):
            return f"frame {s.frame}: hovers - exits = {d}"
    return None


def c_hover_level(t):
    for s in t.samples:
        d = float(sv(s, "hovers")) - float(sv(s, "hover_exits"))
        n = len(hovered_flags(s))
        if n != d:
            return f"frame {s.frame}: {n} toys with pointer_hover, hovers - exits = {d}"
    return None


def c_hover_name(t):
    for s in t.samples:
        d = float(sv(s, "hovers")) - float(sv(s, "hover_exits"))
        h = sv(s, "hovered")
        if (d == 1.0) != (h != ""):
            return f"frame {s.frame}: hovered {h!r} with hovers - exits = {d}"
        if h and h not in [f"toy{i}" for i in range(len(toys(s)))]:
            return f"frame {s.frame}: hovered {h!r} is not a toy index"
    return None


def c_hover_needs_motion(t):
    allowed = set(frames_of(t, "move")) | set(frames_of(t, "button"))
    for a, b in pairs(t.samples):
        if float(sv(b, "hovers")) > float(sv(a, "hovers")) and b.frame not in allowed:
            return f"hover enter at frame {b.frame} with no pointer input that frame"
    return None


def c_hover_at_moves(t):
    checked = 0
    for f in frames_of(t, "move"):
        s = next((x for x in t.samples if x.frame == f), None)
        if s is None:
            continue
        strict, loose = under_pointer(s)
        if strict != loose:
            continue
        ph = hovered_flags(s)
        checked += 1
        if strict and (len(ph) != 1 or ph[0] not in strict):
            return f"frame {f}: toys {strict} under the pointer, hovered flags {ph}"
        if not strict and ph:
            return f"frame {f}: no toy under the pointer, hovered flags {ph}"
    return True if checked else "no unambiguous move frame"


def c_hover_topmost(t):
    hits = 0
    for f in frames_of(t, "move"):
        s = next((x for x in t.samples if x.frame == f), None)
        if s is None:
            continue
        strict, loose = under_pointer(s)
        if not strict or strict != loose:
            continue
        hits += 1
        top = max(strict)
        if hovered_flags(s) != [top] or sv(s, "hovered") != f"toy{top}":
            return (f"frame {f}: under {strict}, flags {hovered_flags(s)}, "
                    f"hovered {sv(s, 'hovered')!r}; expected toy{top} (last created)")
    return True if hits else "assumption failed: no grid point landed on a toy"


def c_hovered_under_pointer(t):
    for s in t.samples:
        mx, my = sv(s, "mouse")
        tt = toys(s)
        for i in hovered_flags(s):
            if math.hypot(tt[i][X] - mx, tt[i][Y] - my) > R_TOY + 0.5:
                return f"frame {s.frame}: toy{i} hovered but not under the pointer"
    return None


def c_some_hover(t):
    return True if float(t.end("hovers")) > 0 else \
        "assumption failed: the grid never touched a toy (seeded placement)"


def _free(a_pos, b_pos, others_a, others_b, en, sol):
    for (x, y) in (a_pos, b_pos):
        if d_bumper(x, y) <= R_TOY + 5 or d_rect(x, y, GLUE) <= R_TOY + 5:
            return False
        if en and d_walls(x, y) <= R_TOY + 5:
            return False
    if en and sol:
        for (ox, oy) in others_a:
            if math.hypot(ox - a_pos[0], oy - a_pos[1]) <= 2 * R_TOY + 5:
                return False
        for (ox, oy) in others_b:
            if math.hypot(ox - b_pos[0], oy - b_pos[1]) <= 2 * R_TOY + 5:
                return False
    return True


def c_free_flight(t):
    n = 0
    for a, b in pairs(t.samples):
        dt = b.time - a.time
        en, sol = sv(b, "resolve_enabled"), sv(b, "solid")
        ma, mb = by_sid(a), by_sid(b)
        for sid, ea in ma.items():
            eb = mb.get(sid)
            if eb is None:
                continue
            oa = [(e[X], e[Y]) for k, e in ma.items() if k != sid]
            ob = [(e[X], e[Y]) for k, e in mb.items() if k != sid]
            if not _free((ea[X], ea[Y]), (eb[X], eb[Y]), oa, ob, en, sol):
                continue
            n += 1
            want = (ea[X] + ea[VX] * dt, ea[Y] + ea[VY] * dt)
            if not close((eb[X], eb[Y]), want, 1e-6):
                return (f"frame {b.frame}: free toy at ({eb[X]:.4f}, {eb[Y]:.4f}), "
                        f"expected ({want[0]:.4f}, {want[1]:.4f})")
            if not close((eb[VX], eb[VY]), (ea[VX], ea[VY]), 1e-9):
                return f"frame {b.frame}: free toy velocity changed"
    return None


def c_glue_slow(t):
    for a, b in pairs(t.samples):
        dt = b.time - a.time
        thr = 0.5 * float(sv(b, "speed"))
        en, sol = sv(b, "resolve_enabled"), sv(b, "solid")
        ma, mb = by_sid(a), by_sid(b)
        for sid, ea in ma.items():
            eb = mb.get(sid)
            if eb is None:
                continue
            if not (d_rect(ea[X], ea[Y], GLUE) < R_TOY - 3 and
                    d_rect(eb[X], eb[Y], GLUE) < R_TOY - 3):
                continue
            ok = True
            for (x, y) in ((ea[X], ea[Y]), (eb[X], eb[Y])):
                if d_bumper(x, y) <= R_TOY + 5 or (en and d_walls(x, y) <= R_TOY + 5):
                    ok = False
            if ok and en and sol:
                for k, e in ma.items():
                    if k != sid and math.hypot(e[X] - ea[X], e[Y] - ea[Y]) <= 2 * R_TOY + 5:
                        ok = False
                for k, e in mb.items():
                    if k != sid and math.hypot(e[X] - eb[X], e[Y] - eb[Y]) <= 2 * R_TOY + 5:
                        ok = False
            if not ok:
                continue
            spd = math.hypot(ea[VX], ea[VY])
            if spd > thr + 1e-6:
                want = (0.98 * ea[VX], 0.98 * ea[VY])
            elif spd < thr - 1e-6:
                want = (ea[VX], ea[VY])
            else:
                continue
            if not close((eb[VX], eb[VY]), want, 1e-6):
                return (f"frame {b.frame}: toy in glue at speed {spd:.3f} (threshold {thr}) "
                        f"vel ({eb[VX]:.4f}, {eb[VY]:.4f}), expected "
                        f"({want[0]:.4f}, {want[1]:.4f})")
            pos = (ea[X] + ea[VX] * dt, ea[Y] + ea[VY] * dt)
            if not close((eb[X], eb[Y]), pos, 1e-6):
                return f"frame {b.frame}: toy in glue did not move by its old vel * dt"
    return None


def c_ke_nonincreasing(t):
    for a, b in pairs(t.samples):
        ka, kb = ke(a), ke(b)
        if kb > ka * (1 + 1e-6) + 1e-6:
            return f"frame {b.frame}: sum |v|^2 rose {ka:.4f} -> {kb:.4f}"
    return None


def c_ke_constant(t):
    s1 = t.samples[0]
    n, sp = len(toys(s1)), float(sv(s1, "speed"))
    k0 = n * sp * sp
    if float(sv(s1, "glue_frames")) == 0 and not close(ke(s1), k0, 1e-6 * k0 + 1e-6):
        return f"frame 1: sum |v|^2 {ke(s1):.4f}, spawn gave {k0:.4f}"
    for a, b in pairs(t.samples):
        if float(sv(b, "glue_frames")) != float(sv(a, "glue_frames")):
            continue
        ka, kb = ke(a), ke(b)
        if abs(kb - ka) > 1e-6 * max(ka, 1.0):
            return f"frame {b.frame}: sum |v|^2 {ka:.6f} -> {kb:.6f} with no glue stay"
    return None


def _inside(s, slop=4.0):
    for e in toys(s):
        if not (42 - slop <= e[X] <= 958 + slop and 42 - slop <= e[Y] <= 658 + slop):
            return f"frame {s.frame}: toy centre ({e[X]:.2f}, {e[Y]:.2f}) outside the walls"
    return None


def c_inside(t):
    start = _start(t)
    p0 = None
    pf = frames_of(t, "P", t.press_frame)
    if pf:
        p0 = pf[0]
    for s in t.samples:
        if s.frame < start:
            continue
        if p0 is not None and s.frame >= p0:
            break
        m = _inside(s)
        if m:
            return m
    return None


def c_no_deep_overlap(t):
    start = _start(t)
    since = 1
    prev_ok = True
    for s in t.samples:
        ok = bool(sv(s, "solid")) and bool(sv(s, "resolve_enabled"))
        if ok and not prev_ok:
            since = s.frame
        prev_ok = ok
        if not ok or s.frame < max(start, since + 10):
            continue
        tt = toys(s)
        for i in range(len(tt)):
            for j in range(i + 1, len(tt)):
                d = math.hypot(tt[i][X] - tt[j][X], tt[i][Y] - tt[j][Y])
                if d < 2 * R_TOY - 4:
                    return f"frame {s.frame}: toys {i},{j} centres {d:.2f} apart"
    return None


def _stay_count(t, dist, counter, start):
    for a, b in pairs(t.samples):
        if b.frame < start:
            continue
        da = [dist(e[X], e[Y]) - R_TOY for e in toys(a)]
        db = [dist(e[X], e[Y]) - R_TOY for e in toys(b)]
        if any(abs(x) <= 3 for x in da + db):
            continue
        n = sum(1 for x, y in zip(da, db) if x < -3 and y < -3)
        got = float(sv(b, counter)) - float(sv(a, counter))
        if got != n:
            return f"frame {b.frame}: {counter} +{got}, {n} toys overlapping on both frames"
    return None


def _exit_bound(t, dist, counter):
    for a, b in pairs(t.samples):
        got = float(sv(b, counter)) - float(sv(a, counter))
        n = sum(1 for e in toys(a) if dist(e[X], e[Y]) - R_TOY <= 3)
        if got < 0 or got > n:
            return f"frame {b.frame}: {counter} +{got}, only {n} toys were overlapping"
    return None


def c_pad_stay(t):
    return _stay_count(t, d_pad, "pad_frames", max(_start(t), 30))


def c_pad_exit(t):
    return _exit_bound(t, d_pad, "pad_exits")


def c_glue_stay(t):
    return _stay_count(t, lambda x, y: d_rect(x, y, GLUE), "glue_frames", max(_start(t), 30))


def c_glue_exit(t):
    return _exit_bound(t, lambda x, y: d_rect(x, y, GLUE), "glue_exits")


def c_bumps(t):
    for a, b in pairs(t.samples):
        got = float(sv(b, "bumps")) - float(sv(a, "bumps"))
        n = sum(1 for e in toys(b) if d_bumper(e[X], e[Y]) - R_TOY <= 3)
        if got < 0:
            return f"frame {b.frame}: bumps decreased"
        if got > n:
            return f"frame {b.frame}: bumps +{got}, {n} toys near the bumper"
    return None


def c_bump_point(t):
    for a, b in pairs(t.samples):
        if float(sv(b, "bumps")) == float(sv(a, "bumps")):
            continue
        x, y = sv(b, "bump_point")
        if not (474 - 3 <= x <= 526 + 3 and 430 - 3 <= y <= 546 + 3):
            return f"frame {b.frame}: bump point ({x:.2f}, {y:.2f}) off the bumper"
        if not any(math.hypot(e[X] - x, e[Y] - y) <= R_TOY + 3 for e in toys(b)):
            return f"frame {b.frame}: bump point ({x:.2f}, {y:.2f}) not on any toy"
    return None


def c_wall_side(t):
    near = {"bottom": lambda e: e[Y] <= 42 + 5, "top": lambda e: e[Y] >= 658 - 5,
            "left": lambda e: e[X] <= 42 + 5, "right": lambda e: e[X] >= 958 - 5}
    for s in t.samples:
        if sv(s, "wall_side") not in ("", "top", "bottom", "left", "right"):
            return f"frame {s.frame}: wall_side {sv(s, 'wall_side')!r}"
    for a, b in pairs(t.samples):
        w = sv(b, "wall_side")
        if w == sv(a, "wall_side") or w == "":
            continue
        if not any(near[w](e) for e in toys(a) + toys(b)):
            return f"frame {b.frame}: wall_side became {w!r} with no toy at that wall"
    return None


def _toggle(t, keyname, probe):
    pf = frames_of(t, keyname, t.press_frame)
    if len(pf) < 2:
        return f"expected two {keyname} presses, saw {pf}"
    r0, r1 = pf[0], pf[1]
    for s in t.samples:
        want = not (r0 <= s.frame < r1)
        if bool(sv(s, probe)) != want:
            return f"frame {s.frame}: {probe} {sv(s, probe)}, expected {want} ({keyname} at {pf})"
    return None


def c_solid_toggle(t):
    return _toggle(t, "R", "solid")


def c_pause_toggle(t):
    return _toggle(t, "P", "resolve_enabled")


def c_pause_wall_side(t):
    pf = frames_of(t, "P", t.press_frame)
    if len(pf) < 2:
        return f"expected two P presses, saw {pf}"
    vals = {sv(s, "wall_side") for s in t.samples if pf[0] + 2 <= s.frame < pf[1]}
    if len(vals) > 1:
        return f"wall_side changed while resolution was off: {vals}"
    return None


def c_scan(t):
    presses = frames_of(t, "left", t.press_frame)
    releases = frames_of(t, "left", t.release_frame)
    if not releases:
        return "no click delivered"
    frame_of = {s.frame: s for s in t.samples}
    for a, b in pairs(t.samples):
        if float(sv(b, "scanned")) != float(sv(a, "scanned")) and b.frame not in releases:
            return f"frame {b.frame}: scanned changed with no click release"
    for pf, rf in zip(presses, releases):
        before_press, before_rel, after = frame_of.get(pf - 1), frame_of.get(rf - 1), frame_of.get(rf)
        if before_press is None or before_rel is None or after is None:
            continue
        cover = any(math.hypot(e[X] - SCAN_PT[0], e[Y] - SCAN_PT[1]) <= R_TOY + 0.5
                    for s in (before_press, before_rel) for e in toys(s))
        if cover:
            continue
        strict = sum(1 for e in toys(before_rel) if e[LOOSE] and
                     d_rect(e[X], e[Y], SCANNER) < R_TOY - 0.5)
        loose = sum(1 for e in toys(before_rel) if e[LOOSE] and
                    d_rect(e[X], e[Y], SCANNER) <= R_TOY + 0.5)
        if strict != loose:
            continue
        if float(sv(after, "scanned")) != strict:
            return f"click released at frame {rf}: scanned {sv(after, 'scanned')}, {strict} loose toys touch the scanner"
    return None


def c_cells(t):
    cells = frames_of(t, "cell")
    sp = frames_of(t, "SPACE", t.press_frame)
    up = frames_of(t, "U", t.press_frame)
    if len(cells) != 3 or len(sp) != 1 or len(up) != 2:
        return f"inputs: cells {cells}, SPACE {sp}, U {up}"
    c0, c1, c2 = cells
    for s in t.samples:
        f, ch, b = s.frame, float(sv(s, "changes")), float(sv(s, "binned"))
        if f < c0 and (ch != 0 or b != 0):
            return f"frame {f}: changes {ch} binned {b} before any write"
        if c0 + 2 <= f < sp[0] and (ch != 1 or b != 3):
            return f"frame {f}: changes {ch} binned {b}; expected 1 / 3 (second write of 3 is no change)"
        if sp[0] + 2 <= f and ch != 2:
            return f"frame {f}: changes {ch}, expected 2 (SPACE 3->0; after U no more)"
        if sp[0] <= f < c2 and b != 0:
            return f"frame {f}: binned {b}, expected 0 after SPACE"
        if f >= c2 + 1 and b != 7:
            return f"frame {f}: binned {b}, expected 7"
        if f >= up[0] and sv(s, "watching"):
            return f"frame {f}: still watching after U"
        if f < up[0] and not sv(s, "watching"):
            return f"frame {f}: watching False before U"
    return None


def c_still(t):
    ref = next(s for s in t.samples if s.frame == 60)
    rb = float(sv(ref, "bumps"))
    rp = {k: (e[X], e[Y]) for k, e in by_sid(ref).items()}
    for s in t.samples:
        if float(sv(s, "glue_frames")) != 0:
            return f"frame {s.frame}: glue_frames {sv(s, 'glue_frames')} with still toys"
        if s.frame < 60:
            continue
        if float(sv(s, "bumps")) != rb:
            return f"frame {s.frame}: bumps changed with still toys"
        for k, e in by_sid(s).items():
            if not close((e[X], e[Y]), rp[k], 0.5):
                return f"frame {s.frame}: still toy moved from {rp[k]} to ({e[X]:.2f}, {e[Y]:.2f})"
    return None


def c_layers(t):
    v = sv(t.samples[0], "layers")
    if tuple(float(x) for x in v) != (-1.0, -1.0, -1.0, -1.0, 1.0):
        return f"layers {v}"
    return None


# ---------------------------------------------------------------- expectations
SHAPES = "design/Shapes Design.md"
G = "docs/pt/guide/index.html"

EXPECT = [
    Expect(id="E1", level="L0", cite="toybox.py spawn(); " + G + "#mundo-grupos",
           text="At frame 1 there are st.count toys, all tagged loose.",
           check=custom(c_startup_counts), scenarios=("*",)),
    Expect(id="E2", level="L0", cite="toybox.py PARAMS.get defaults",
           text="Without PARAMS the program spawns 6 toys at speed 160.",
           check=custom(c_defaults), scenarios=("idle",)),
    Expect(id="E3", level="L0", cite=G + "#colisao-resolve (STATIC = float('inf'))",
           text="There are 4 walls and every wall's mass is STATIC (infinite).",
           check=custom(c_walls), scenarios=("idle",)),
    Expect(id="E4", level="L0", cite=G + "#colisao-resolve (.mass)",
           text="Every toy keeps radius 22 and mass 1.0 on every frame.",
           check=custom(c_toy_body), scenarios=("*",)),
    Expect(id="E5", level="L0", cite=G + "#mundo-camadas (below('default') = -1, above('default') = 1)",
           text="Bins, glue and pad sit on layer -1; the ring on layer 1.",
           check=custom(c_layers), scenarios=("idle",)),
    Expect(id="E6", level="L0", cite=G + "#colisao-corpo (Collider.shapes)",
           text="The bumper Collider has two live shapes.",
           check=at(1, "bumper_n", lambda v: v == 2), scenarios=("idle",)),
    Expect(id="E7", level="L0", cite="toybox.py st setup; " + G + "#colisao-resolve (resolve_enabled default True)",
           text="At frame 1 the counters are 0, flushed/watching/solid are True and resolution is enabled.",
           check=custom(c_initial_state), scenarios=("*",)),
    Expect(id="E8", level="L2", cite="toybox.py spawn(); " + G + "#colisao-resolve",
           text="At frame 1 every toy centre is in the spawn box x 80..920, y 400..580 grown by 28 "
                "(one two-body separation 22 + one frame of motion <= 2.7 + 3 slop).",
           check=custom(c_spawn_region), scenarios=FEW_TOYS),
    Expect(id="E9", level="L0", cite=SHAPES + "#drag-and-drop (3. release without having dragged)",
           text="With no drag (only moves and in-place clicks) no drag_over / drag_to / drop_by runs: "
                "drops, misses, over_frames stay 0 and the ring stays hidden at (-100, -100).",
           check=custom(c_no_drag), scenarios=("*",)),
    Expect(id="E10", level="L0", cite="toybox.py update(); " + G + "#mundo-grupos",
           text="Nothing is binned: flushed stays True, in_red/in_blue stay 0, every toy stays loose.",
           check=custom(c_bins_untouched), scenarios=("*",)),
    Expect(id="E11", level="L0", cite="Scena Design.md#pull-reactivity; toybox.py status formula",
           text="The status Text always shows the formula of the current st values "
                "(assumes a cell formats as its value in an f-string and layer ints print as -1/1).",
           check=custom(c_text), scenarios=("*",), guess=True),
    Expect(id="E12", level="L0", cite=SHAPES + "#hover-pointer_hover-hover--hover_exit (one target; every enter has one exit)",
           text="hovers - hover_exits is always 0 or 1.",
           check=custom(c_hover_balance), scenarios=("*",)),
    Expect(id="E13", level="L0", cite=SHAPES + "#hover-pointer_hover-hover--hover_exit (pointer_hover is the level)",
           text="The number of toys with pointer_hover equals hovers - hover_exits on every frame.",
           check=custom(c_hover_level), scenarios=("*",)),
    Expect(id="E14", level="L0", cite=SHAPES + "#hover-pointer_hover-hover--hover_exit",
           text="st.hovered is non-empty exactly while a toy is hovered and names a toy index "
                "(assumes the old target's exit runs before the new target's enter).",
           check=custom(c_hover_name), scenarios=("*",), guess=True),
    Expect(id="E15", level="L0", cite=G + "#reagir-pointer (a entrada espera o mouse se mexer)",
           text="A hover enter happens only on a frame where a pointer input was delivered; a toy "
                "sliding under a still cursor gains no hover.",
           check=custom(c_hover_needs_motion), scenarios=("*",)),
    Expect(id="E16", level="L0", cite=SHAPES + "#hover-pointer_hover-hover--hover_exit (full hit test when the pointer moved)",
           text="On each move frame a toy is hovered iff a toy covers the pointer (0.5 DU ambiguity band skipped).",
           check=custom(c_hover_at_moves), scenarios=("hover",)),
    Expect(id="E17", level="L0", cite=SHAPES + "#hit-testing (within a layer later-drawn wins)",
           text="Where toys overlap under the pointer, the hovered one is the last created "
                "(assumes draw order = creation order = group index order).",
           check=custom(c_hover_topmost), scenarios=("hover",), guess=True),
    Expect(id="E18", level="L0", cite=SHAPES + "#hover-pointer_hover-hover--hover_exit (exit is immediate)",
           text="A hovered toy always covers the pointer (within 0.5 DU) after the frame.",
           check=custom(c_hovered_under_pointer), scenarios=("idle", "still", "hover", "ghost", "pause", "cells")),
    Expect(id="E19", level="L0", cite="scenario design (seeded placement)",
           text="Sanity: the hover grid sweep hovers at least one toy (assumes 20 still toys cover a grid point).",
           check=custom(c_some_hover), scenarios=("hover",), guess=True),
    Expect(id="E20", level="L1", cite="toybox.py update(); Scena Design.md#frame-order; " + G + "#colisao-resolve",
           text="A toy clear (by 5 DU) of bumper, glue, walls (when resolution is on) and other toys "
                "(when solid and on) moves exactly by vel*dt and keeps its velocity.",
           check=custom(c_free_flight), scenarios=FEW_TOYS),
    Expect(id="E21", level="L1", cite=G + "#colisao-collide (collide_with_stay: every following frame)",
           text="A free toy staying in the glue with speed above speed/2 has its velocity scaled by 0.98 "
                "that frame; below speed/2 it is unchanged.",
           check=custom(c_glue_slow), scenarios=("idle", "ghost", "pause", "cells")),
    Expect(id="E22", level="L2", cite=G + "#colisao-resolve (bounce=1.0 elastico; >1 super-quique)",
           text="The sum of toy |v|^2 never rises (elastic bounces, reflection off the bumper, glue only slows).",
           check=custom(c_ke_nonincreasing), scenarios=("*",)),
    Expect(id="E23", level="L1", cite=G + "#colisao-resolve (bounce=1.0 elastico)",
           text="Sum of |v|^2 is count*speed^2 at frame 1 and is unchanged on every frame with no glue stay "
                "(assumes elastic equal-mass contacts conserve kinetic energy exactly).",
           check=custom(c_ke_constant), scenarios=("*",), guess=True),
    Expect(id="E24", level="L2", cite=G + "#colisao-resolve; Scena Design.md#collision (motion is swept)",
           text="While resolution is on, toy centres stay inside the walls (x 42..958, y 42..658) "
                "with 4 DU slop for toy-toy pushes (not swept).",
           check=custom(c_inside), scenarios=("idle", "still", "hover", "scan", "ghost", "cells", "pause")),
    Expect(id="E25", level="L2", cite=G + "#colisao-resolve (desfaz o que sobrou de sobreposicao)",
           text="While solid and enabled (from 10 frames after it became so; 60 for 20 toys), "
                "toy centres are at least 44 - 4 DU apart.",
           check=custom(c_no_deep_overlap), scenarios=("*",)),
    Expect(id="E26", level="L0", cite=G + "#colisao-collide (stay: each following frame)",
           text="pad_frames rises each frame by the number of toys overlapping the pad on that and the "
                "previous frame (frames with a toy within 3 DU of contact skipped).",
           check=custom(c_pad_stay), scenarios=("*",)),
    Expect(id="E27", level="L2", cite=G + "#colisao-collide (exit)",
           text="pad_exits never rises by more than the toys overlapping the pad (3 DU slop) the frame before.",
           check=custom(c_pad_exit), scenarios=("*",)),
    Expect(id="E28", level="L0", cite=G + "#colisao-collide (collide_with_stay)",
           text="glue_frames rises each frame by the number of toys overlapping the glue on that and the "
                "previous frame (ambiguous frames skipped).",
           check=custom(c_glue_stay), scenarios=("*",)),
    Expect(id="E29", level="L2", cite=G + "#colisao-collide (collide_with_exit)",
           text="glue_exits never rises by more than the toys overlapping the glue the frame before.",
           check=custom(c_glue_exit), scenarios=("*",)),
    Expect(id="E30", level="L2", cite=G + "#colisao-corpo (Collider fires once per body); #colisao-collide (enter)",
           text="bumps never falls and rises per frame by at most the toys within 3 DU of the bumper.",
           check=custom(c_bumps), scenarios=("*",)),
    Expect(id="E31", level="L2", cite=G + "#colisao-collide (CollisionInfo.point: midpoint of contacts)",
           text="On a bump frame bump_point lies in the bumper's box (x 474..526, y 430..546, 3 DU slop) "
                "and within 25 of a toy centre.",
           check=custom(c_bump_point), scenarios=("*",)),
    Expect(id="E32", level="L2", cite=G + "#colisao-touching (side of this body; previous frame's check)",
           text="wall_side is '', top, bottom, left or right, and becomes a side only when a toy is "
                "within 5 DU of that wall.",
           check=custom(c_wall_side), scenarios=("*",)),
    Expect(id="E33", level="L0", cite="toybox.py on_key_down R; " + G + "#colisao-resolve (unresolve)",
           text="R makes st.solid False from its press frame until the second R makes it True.",
           check=custom(c_solid_toggle), scenarios=("ghost",)),
    Expect(id="E34", level="L0", cite=G + "#colisao-resolve (collision.resolve_enabled)",
           text="P turns collision.resolve_enabled off from its press frame until the second P.",
           check=custom(c_pause_toggle), scenarios=("pause",)),
    Expect(id="E35", level="L0", cite=G + "#colisao-resolve (touching_* fica vazio enquanto desligado)",
           text="While resolution is off, wall_side does not change (touching_contacts is empty).",
           check=custom(c_pause_wall_side), scenarios=("pause",)),
    Expect(id="E36", level="L0", cite=SHAPES + "#click; " + G + "#colisao-corpo (test_collision)",
           text="A scanner click sets scanned, on its release frame, to the loose toys touching the scanner "
                "(clicks with a toy over the point or a toy within 0.5 DU of contact skipped); scanned "
                "changes at no other frame.",
           check=custom(c_scan), scenarios=("scan", "still")),
    Expect(id="E37", level="L0", cite=G + "#reagir-on-change; #reagir-when (unregister_event)",
           text="on_change(st['binned']) runs once per real change: write 3 -> 1, write 3 again -> no run, "
                "SPACE (3 -> 0) -> 2, after U writing 7 -> still 2; watching False from U on.",
           check=custom(c_cells), scenarios=("cells",)),
    Expect(id="E38", level="L2", cite="toybox.py spawn(speed=0); " + G + "#colisao-resolve",
           text="With speed 0 no toy reaches the glue, and from frame 60 toys stay put (0.5 DU) and bumps is constant.",
           check=custom(c_still), scenarios=("still",)),
]
