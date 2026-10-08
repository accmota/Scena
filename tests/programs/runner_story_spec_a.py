"""Spec A for tests/programs/runner_story.py (written from the docs only).

Premises used throughout (from the program text):
  W, H = 1000, 600; GROUND = 60; hero 40x40 at (200, 80); GRAVITY 1500; JUMP 620;
  track slots step 300 (ground 300x60, spike 30x50 at y 85 in slots >= 2, coin r=10
  at y 190 in slots >= 1); default SPEED 260; default lives 3; Endless seed 7.
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close, serial)
import math

FILES_READ = [
    "tests/programs/spec_agent_prompt.txt",
    "tests/programs/runner_story.py",
    "design/Scena Design.md#frame-order",
    "design/Scena Design.md#scheduler",
    "design/Canvas Design.md#layer-view",
    "design/Canvas Design.md#endless-fill",
    "docs/pt/guide/index.html#mundo-sem-fim",
    "docs/pt/guide/index.html#mundo-camadas",
    "docs/pt/guide/index.html#frame-clock",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#ui-textinput",
    "docs/pt/guide/index.html#mover-tween",
    "docs/pt/guide/index.html#mover-pose",
    "docs/pt/guide/index.html#agendar (after / every)",
    "docs/pt/guide/index.html#mode-enter",
    "docs/pt/guide/index.html#mode-async",
    "docs/pt/guide/index.html#mode-cancela",
    "docs/pt/guide/index.html#som-audio (audio.level, amp_db)",
    "docs/pt/guide/index.html#aparencia-cor",
    "docs/pt/guide/index.html (set_defaults, Rect props, canvas.playfield, canvas.pan_x)",
]

DT = 1.0 / 60.0
EPS = 1e-6


def _rgb3(p, c):
    rgb = getattr(c, "rgb", None)
    if rgb is None:
        rgb = p.Color(c).rgb
    return tuple(round(float(v), 3) for v in tuple(rgb)[:3])


def _mode_name(p):
    m = p.director.mode
    return None if m is None else getattr(m, "__name__", repr(m))


PROBES = {
    "phase": lambda p: p.st.phase,
    "lives": lambda p: p.st.lives,
    "coins": lambda p: p.st.coins,
    "distance": lambda p: p.st.distance,
    "countdown": lambda p: p.st.countdown,
    "skipped": lambda p: p.st.skipped,
    "player_name": lambda p: p.st.player_name,
    "runs_ended": lambda p: p.st.runs_ended,
    "mode": _mode_name,
    "SPEED": lambda p: p.SPEED,
    "NAME_WAIT": lambda p: p.PARAMS.get("name_wait", 6.0),
    "hero": lambda p: (p.hero.center.x, p.hero.center.y),
    "hero_angle": lambda p: p.hero.angle,
    "hero_style": lambda p: (_rgb3(p, p.hero.color), p.hero.line_width),
    "ref_rgb": lambda p: (_rgb3(p, "dim gray"), _rgb3(p, "orange")),
    "pan": lambda p: (p.canvas.pan_x, p.canvas.pan_y),
    "gv": lambda p: (p.canvas.game_view.left, p.canvas.game_view.right,
                     p.canvas.game_view.bottom, p.canvas.game_view.top),
    "pf": lambda p: (p.canvas.playfield.left, p.canvas.playfield.right,
                     p.canvas.playfield.bottom, p.canvas.playfield.top),
    "dust": lambda p: (p.dust.center.x, p.dust.center.y),
    "haze": lambda p: (p.haze.center.x, p.haze.center.y),
    "meter": lambda p: (p.meter.center.x, p.meter.center.y, p.meter.height),
    "hud": lambda p: p.hud.text,
    "count_text": lambda p: p.count_text.text,
    "result": lambda p: p.result.text,
    "title": lambda p: (p.title.center.x, p.title.center.y, bool(p.title.visible)),
    "hint": lambda p: (p.hint.center.x, p.hint.center.y, bool(p.hint.visible)),
    "name_vis": lambda p: bool(p.name_box.visible),
    "name_focus": lambda p: bool(p.name_box.focused),
    "scale": lambda p: p.clock.scale,
    "paused": lambda p: bool(p.clock.paused),
    "clouds_scroll": lambda p: p.canvas.layers["clouds"].scroll,
    "layers": lambda p: (p.canvas.layers["track"].z, p.canvas.layers["clouds"].z,
                         p.dust.layer, p.haze.layer, p.hero.layer, p.title.layer),
    "piece_layers": lambda p: (tuple(sorted(set(str(x.layer) for x in p.track.pieces))),
                               tuple(sorted(set(str(x.layer) for x in p.sky.pieces))),
                               len(p.sky.pieces)),
    "ground": lambda p: tuple((g.center.x, g.center.y, g.width, g.height, _rgb3(p, g.color))
                              for g in p.group["ground"]),
    "spikes": lambda p: tuple((serial(s), s.center.x, s.center.y) for s in p.group["spike"]),
    "coin_list": lambda p: tuple((serial(c), c.center.x, c.center.y, c.stretch)
                                 for c in p.group["coin"]),
    "taken": lambda p: len(p.taken),
}


# ---------------------------------------------------------------- helpers ----

def _rows(t, names):
    cols = {n: t.series(n) for n in names}
    base = cols[names[0]]
    out = []
    for i, (f, tm, _) in enumerate(base):
        out.append((f, tm, {n: cols[n][i][2] for n in names}))
    return out


def _safe(fn):
    def run(t):
        try:
            return fn(t)
        except Exception as e:  # a crash in a check is a failure, with the reason
            return "check raised %s: %s" % (type(e).__name__, e)
    return run


def _near(a, b, tol):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_near(x, y, tol) for x, y in zip(a, b))
    return abs(float(a) - float(b)) <= tol


def _i(v):
    return int(round(float(v)))


def _first(R, pred):
    for k, (f, tm, v) in enumerate(R):
        if pred(v):
            return k
    return None


def _t0(R):
    k = _first(R, lambda v: v["phase"] == "intro")
    return None if k is None else R[k][1]


def _frame_index(R, frame):
    for k, (f, tm, v) in enumerate(R):
        if f == frame:
            return k
    return None


NO_JUMP = ("idle", "early_space", "skip", "pause_run", "pause_intro",
           "outro_anon", "outro_named", "outro_p")
SKIPPED = ("skip", "jump", "pause_run", "outro_anon", "outro_named", "outro_p")
OUTRO = ("outro_anon", "outro_named", "outro_p")
NO_PAUSE = ("idle", "early_space", "skip", "jump", "outro_anon", "outro_named")
ORDER_PHASE = ["boot", "intro", "run", "outro", "done"]
ORDER_MODE = [None, "intro", "running", "outro", None]
MODE_OF_PHASE = {"boot": None, "intro": "intro", "run": "running", "outro": "outro",
                 "done": None}


def _compress(seq):
    out = []
    for x in seq:
        if not out or out[-1] != x:
            out.append(x)
    return out


# ----------------------------------------------------------------- checks ----

@_safe
def c_start_state(t):
    R = _rows(t, ["phase", "coins", "distance", "runs_ended", "mode", "skipped",
                  "player_name", "countdown", "result", "name_vis"])
    f, tm, v = R[0]
    if v["phase"] != "boot":
        return "frame 1 phase %r" % v["phase"]
    if _i(v["coins"]) != 0 or _i(v["distance"]) != 0 or _i(v["runs_ended"]) != 0:
        return "frame 1 counters %r" % ((v["coins"], v["distance"], v["runs_ended"]),)
    if v["mode"] is not None or v["skipped"] is not False or v["player_name"] != "":
        return "frame 1 mode/skipped/name %r" % ((v["mode"], v["skipped"], v["player_name"]),)
    if not _near(v["countdown"], 3.0, 1e-9) or v["result"] != "" or v["name_vis"]:
        return "frame 1 countdown/result/name_box %r" % ((v["countdown"], v["result"], v["name_vis"]),)
    return None


def c_lives_start(expected):
    @_safe
    def chk(t):
        v = t.series("lives")[0][2]
        return None if _i(v) == expected else "frame-1 lives %r, expected %d" % (v, expected)
    return chk


@_safe
def c_intro_start(t):
    R = _rows(t, ["phase"])
    for f, tm, v in R:
        if v["phase"] == "intro":
            if 0.3 - 1e-6 <= tm <= 0.3 + DT + 1e-6:
                return None
            return "intro began at t=%.4f (frame %d)" % (tm, f)
        if v["phase"] != "boot":
            return "phase %r before intro at frame %d" % (v["phase"], f)
    return "intro never began"


@_safe
def c_phase_order(t):
    seq = _compress(v for f, tm, v in t.series("phase"))
    if seq != ORDER_PHASE[:len(seq)]:
        return "phase sequence %r" % seq
    return None


@_safe
def c_mode_matches_phase(t):
    R = _rows(t, ["phase", "mode"])
    for f, tm, v in R:
        if MODE_OF_PHASE.get(v["phase"], "?") != v["mode"]:
            return "frame %d: phase %r with mode %r" % (f, v["phase"], v["mode"])
    seq = _compress(v["mode"] for f, tm, v in R)
    if seq != ORDER_MODE[:len(seq)]:
        return "mode sequence %r" % seq
    return None


@_safe
def c_hint_linear(t):
    R = _rows(t, ["phase", "hint"])
    t0 = _t0(R)
    if t0 is None:
        return "no intro"
    for f, tm, v in R:
        if v["phase"] == "intro" and t0 <= tm <= t0 + 0.8:
            u = (tm - t0) / 0.8
            hx, hy, vis = v["hint"]
            if not _near(hx, 500, EPS) or abs(hy - (-40 + 400 * u)) > 9.5:
                return "frame %d: hint at %r, expected y~%.1f" % (f, (hx, hy), -40 + 400 * u)
    return None


@_safe
def c_title_hint_end(t):
    R = _rows(t, ["phase", "title", "hint"])
    t0 = _t0(R)
    if t0 is None:
        return "no intro"
    seen_run = False
    for f, tm, v in R:
        if v["phase"] in ("boot",):
            if not _near(v["title"][:2], (500, 700), EPS) or not _near(v["hint"][:2], (500, -40), EPS):
                return "frame %d: title/hint moved before intro" % f
        if v["phase"] == "intro":
            if not (v["title"][2] and v["hint"][2]):
                return "frame %d: title/hint hidden during intro" % f
            if tm >= t0 + 0.8 + 2 * DT:
                if not _near(v["title"][:2], (500, 420), EPS) or not _near(v["hint"][:2], (500, 360), EPS):
                    return "frame %d: title %r hint %r after the 0.8 s tween" % (f, v["title"], v["hint"])
        if v["phase"] in ("run", "outro", "done"):
            seen_run = True
            if v["title"][2] or v["hint"][2]:
                return "frame %d: title/hint still visible in phase %r" % (f, v["phase"])
    return None


@_safe
def c_title_ease_out(t):
    R = _rows(t, ["phase", "title"])
    t0 = _t0(R)
    if t0 is None:
        return "no intro"
    prev = None
    for f, tm, v in R:
        if v["phase"] == "intro" and t0 <= tm <= t0 + 0.8:
            y = v["title"][1]
            u_lag = max(0.0, (tm - t0 - DT) / 0.8)
            if y > 700 - 280 * u_lag + EPS:
                return "frame %d: title y %.2f behind linear %.2f (ease_out should lead)" % (
                    f, y, 700 - 280 * u_lag)
            if prev is not None and y > prev + EPS:
                return "frame %d: title moved back up" % f
            prev = y
    return None


@_safe
def c_countdown_linear(t):
    R = _rows(t, ["phase", "countdown"])
    t0 = _t0(R)
    if t0 is None:
        return "no intro"
    n = 0
    for f, tm, v in R:
        if v["phase"] == "intro" and t0 + 0.8 + 2 * DT <= tm <= t0 + 3.8 - 2 * DT:
            exp = 3.0 - (tm - t0 - 0.8)
            if abs(v["countdown"] - exp) > 0.05:
                return "frame %d: countdown %.3f, expected %.3f" % (f, v["countdown"], exp)
            n += 1
    return None if n else "no countdown samples"


@_safe
def c_count_text(t):
    R = _rows(t, ["phase", "countdown", "count_text"])
    for f, tm, v in R:
        exp = ("%.1f" % v["countdown"]) if v["phase"] == "intro" else ""
        if v["count_text"] != exp:
            return "frame %d: count_text %r, expected %r" % (f, v["count_text"], exp)
    return None


@_safe
def c_run_start_unskipped(t):
    R = _rows(t, ["phase", "countdown", "skipped", "title", "hint"])
    t0 = _t0(R)
    k = _first(R, lambda v: v["phase"] == "run")
    if t0 is None or k is None:
        return "run never started (t0=%r)" % t0
    f, tr, v = R[k]
    if not (3.8 - 1e-6 <= tr - t0 <= 3.8 + 3 * DT):
        return "run began %.4f s after intro (expected 3.8)" % (tr - t0)
    if not _near(v["countdown"], 0.0, 1e-9):
        return "countdown %r at run start" % v["countdown"]
    if any(vv["skipped"] for ff, tt, vv in R):
        return "skipped became True without a skip"
    if v["title"][2] or v["hint"][2]:
        return "title/hint visible at run start"
    return None


@_safe
def c_early_space_ignored(t):
    R = _rows(t, ["phase", "skipped"])
    fs = t.press_frame("SPACE", 0)
    k = _frame_index(R, fs + 5)
    if k is None:
        return "no sample 5 frames after SPACE"
    if R[k][2]["phase"] != "intro" or R[k][2]["skipped"]:
        return "early SPACE changed the intro: %r" % (R[k][2],)
    return None


@_safe
def c_skip(t):
    R = _rows(t, ["phase", "skipped", "title", "hint"])
    fs = t.press_frame("SPACE", 0)
    kb, ka = _frame_index(R, fs - 1), _frame_index(R, fs + 1)
    if R[kb][2]["phase"] != "intro":
        return "assumption failed: phase %r just before the skip SPACE" % R[kb][2]["phase"]
    for f, tm, v in R:
        if f < fs and v["skipped"]:
            return "skipped True before SPACE (frame %d)" % f
        if f >= fs + 1:
            if not v["skipped"]:
                return "frame %d: skipped False after SPACE" % f
            if v["phase"] == "intro" or v["phase"] == "boot":
                return "frame %d: still %r after SPACE" % (f, v["phase"])
            if v["title"][2] or v["hint"][2]:
                return "frame %d: title/hint visible after skip" % f
    if R[ka][2]["phase"] != "run":
        return "phase %r one frame after skip" % R[ka][2]["phase"]
    return None


@_safe
def c_skip_countdown_frozen(t):
    R = _rows(t, ["phase", "countdown"])
    t0 = _t0(R)
    fs = t.press_frame("SPACE", 0)
    ks, ka = _frame_index(R, fs), _frame_index(R, fs + 1)
    c = R[ka][2]["countdown"]
    if not (0.0 < c < 3.0):
        return "countdown %r after skip" % c
    exp = 3.0 - (R[ks][1] - t0 - 0.8)
    if abs(c - exp) > 0.05:
        return "countdown frozen at %.3f, expected about %.3f" % (c, exp)
    for f, tm, v in R[ka:]:
        if not _near(v["countdown"], c, 1e-9):
            return "frame %d: countdown moved after skip (%r)" % (f, v["countdown"])
    return None


@_safe
def c_hero_on_ground(t):
    for f, tm, (x, y) in t.series("hero"):
        if abs(y - 80) > EPS:
            return "frame %d: hero y %.4f (no jump was pressed)" % (f, y)
    return None


@_safe
def c_hero_still_before_run(t):
    R = _rows(t, ["phase", "hero", "hero_angle"])
    for f, tm, v in R:
        if v["phase"] in ("boot", "intro"):
            if not _near(v["hero"], (200, 80), EPS) or not _near(v["hero_angle"], 0, EPS):
                return "frame %d: hero %r angle %r before the run" % (f, v["hero"], v["hero_angle"])
    return None


@_safe
def c_run_motion(t):
    R = _rows(t, ["phase", "hero", "SPEED"])
    for k in range(1, len(R)):
        f, tm, v = R[k]
        pf, ptm, pv = R[k - 1]
        dx = v["hero"][0] - pv["hero"][0]
        if pv["phase"] == "run" and v["phase"] == "run":
            exp = v["SPEED"] * (tm - ptm)
            if abs(dx - exp) > EPS:
                return "frame %d: hero dx %.5f, expected SPEED*dt = %.5f" % (f, dx, exp)
        if pv["phase"] in ("outro", "done") and v["phase"] in ("outro", "done"):
            if abs(dx) > EPS or abs(v["hero"][1] - pv["hero"][1]) > EPS:
                return "frame %d: hero moved after the run ended" % f
    return None


@_safe
def c_camera(t):
    R = _rows(t, ["phase", "hero", "pan", "gv", "haze"])
    pan_y0 = R[0][2]["pan"][1]
    frozen = None
    for f, tm, v in R:
        px, py = v["pan"]
        gcx = (v["gv"][0] + v["gv"][1]) / 2
        # Revised (NUMERIC): game_view goes through the camera's float32
        # matrix (~1e-5 off pan_x); compare view-derived values at 1e-3.
        if not _near(gcx, px, 1e-3):
            return "frame %d: game_view centre x %.3f != pan_x %.3f" % (f, gcx, px)
        if not _near(v["haze"], (gcx, 30), 1e-3):
            return "frame %d: haze %r, view centre x %.3f" % (f, v["haze"], gcx)
        if v["phase"] == "run":
            if not _near(px, v["hero"][0] + 300, EPS) or not _near(py, pan_y0, EPS):
                return "frame %d: pan %r, hero x %.3f" % (f, v["pan"], v["hero"][0])
        elif v["phase"] in ("outro", "done"):
            # the hit frame's update already panned to the hero; from then on the camera holds
            if frozen is None:
                frozen = v["pan"]
                if not _near(px, v["hero"][0] + 300, EPS):
                    return "frame %d: pan %r at the end of the run, hero x %.3f" % (f, v["pan"], v["hero"][0])
            elif not _near(v["pan"], frozen, EPS):
                return "frame %d: camera moved after the run (%r)" % (f, v["pan"])
    return None


@_safe
def c_camera_rest(t):
    v = _rows(t, ["pan", "gv"])[0][2]
    if not _near(v["pan"], (500, 300), EPS) or not _near(v["gv"], (0, 1000, 0, 600), EPS):
        return "frame 1 pan %r view %r" % (v["pan"], v["gv"])
    return None


@_safe
def c_playfield(t):
    R = _rows(t, ["phase", "gv", "pf"])
    prev = None
    for f, tm, v in R:
        # Revised (SPEC-LOGIC): the phase turns "run" during the frame's
        # process tick, after update() ran the intro branch, so the playfield
        # follows the view from the second "run" frame on.
        was_running, prev = prev == "run", v["phase"]
        if v["phase"] == "run" and was_running:
            l, r, b, tp = v["gv"]
            if not _near(v["pf"], (l - 60, r + 60, b - 60, tp + 60), 1e-3):
                return "frame %d: playfield %r, view %r" % (f, v["pf"], v["gv"])
    return None


@_safe
def c_dust(t):
    R = _rows(t, ["hero", "dust"])
    for f, tm, v in R:
        if not _near(v["dust"], (v["hero"][0], 64), EPS):
            return "frame %d: dust %r, hero %r" % (f, v["dust"], v["hero"])
    return None


@_safe
def c_meter(t):
    for f, tm, (mx, my, h) in t.series("meter"):
        if not (4 - EPS <= h <= 104 + EPS):
            return "frame %d: meter height %r" % (f, h)
        if not _near(mx, 970, EPS) or not _near(my - h / 2, 20, EPS):
            return "frame %d: meter centre %r height %r (bottom must be 20)" % (f, (mx, my), h)
    return None


@_safe
def c_hud(t):
    R = _rows(t, ["lives", "coins", "distance", "hud"])
    for f, tm, v in R:
        exp = "Lives %d  Coins %d  Dist %d" % (_i(v["lives"]), _i(v["coins"]), _i(v["distance"]))
        if v["hud"] != exp:
            return "frame %d: hud %r, expected %r" % (f, v["hud"], exp)
    return None


@_safe
def c_layers(t):
    v = t.series("layers")[0][2]
    exp = (-1, -2, 1, -3, "default", "ui")
    for a, b in zip(v, exp):
        if isinstance(b, str):
            if a != b:
                return "layers %r, expected %r" % (v, exp)
        elif not _near(a, b, 1e-9):
            return "layers %r, expected %r" % (v, exp)
    return None


@_safe
def c_piece_layers(t):
    for f, tm, (tl, sl, n) in t.series("piece_layers"):
        if tuple(tl) not in ((), ("track",)) or tuple(sl) not in ((), ("clouds",)):
            return "frame %d: piece layers %r / %r" % (f, tl, sl)
        if n < 1:
            return "frame %d: no cloud pieces" % f
    return None


@_safe
def c_ground_under_hero(t):
    R = _rows(t, ["hero", "ground"])
    for f, tm, v in R:
        hx = v["hero"][0]
        for (gx, gy, gw, gh, rgb) in v["ground"]:
            if not (_near(gy, 30, EPS) and _near(gw, 300, EPS) and _near(gh, 60, EPS)):
                return "frame %d: ground piece %r" % (f, (gx, gy, gw, gh))
        if not any(gx - 150 - EPS <= hx <= gx + 150 + EPS for (gx, gy, gw, gh, rgb) in v["ground"]):
            return "frame %d: no ground under hero x %.2f" % (f, hx)
    return None


@_safe
def c_ground_count(t):
    for f, tm, g in t.series("ground"):
        if not (7 <= len(g) <= 11):
            return "frame %d: %d live ground pieces" % (f, len(g))
    return None


def _slot(x):
    return math.floor(x / 300.0)


@_safe
def c_slot_alignment(t):
    R = _rows(t, ["ground", "spikes", "coin_list"])
    for f, tm, v in R:
        for (gx, gy, gw, gh, rgb) in v["ground"]:
            r = (gx - 150) / 300.0
            if abs(r - round(r)) > 1e-6:
                return "frame %d: ground centre x %.3f not on a 300 grid from 0" % (f, gx)
        for (s, sx, sy) in v["spikes"]:
            r = (sx - 150) / 300.0
            if abs(r - round(r)) > 1e-6 or round(r) < 2 or not _near(sy, 85, EPS):
                return "frame %d: spike at %r" % (f, (sx, sy))
        for (s, cx, cy, st_i) in v["coin_list"]:
            i = _slot(cx)
            if i < 1 or not _near(cy, 190, EPS) or not (40 - EPS <= cx - 300 * i <= 260 + EPS) \
                    or _i(st_i) != i:
                return "frame %d: coin at %r stretch %r" % (f, (cx, cy), st_i)
    return None


@_safe
def c_colors(t):
    R = _rows(t, ["ground", "ref_rgb", "hero_style"])
    dim, orange = R[0][2]["ref_rgb"]
    x1 = set(round(g[0], 3) for g in R[0][2]["ground"])
    hero_rgb, lw = R[0][2]["hero_style"]
    if not _near(hero_rgb, orange, 0.002) or not _near(lw, 2.0, 1e-9):
        return "hero style %r, expected orange / 2.0" % ((hero_rgb, lw),)
    late = 0
    for f, tm, v in R:
        for g in v["ground"]:
            gx, rgb = round(g[0], 3), g[4]
            if gx in x1:
                if not _near(rgb, dim, 0.002):
                    return "frame %d: first-screen ground at x %.1f is %r, expected dim gray" % (f, gx, rgb)
            else:
                late += 1
                if not _near(rgb, orange, 0.002):
                    return ("frame %d: ground built during play at x %.1f is %r, expected orange "
                            "(set_defaults('orange') was the last call)" % (f, gx, rgb))
    return None


@_safe
def c_no_spike_overlap(t):
    R = _rows(t, ["hero", "spikes"])
    for f, tm, v in R:
        hx, hy = v["hero"]
        if hy >= 129.5:
            continue
        for (s, sx, sy) in v["spikes"]:
            if abs(sx - hx) < 34.5:
                return "frame %d: live spike at x %.1f overlaps hero x %.1f" % (f, sx, hx)
    return None


def _near_vanish(R, list_key, reach_x, reach_y):
    """Frames where an item of list_key disappeared next to the hero (count per frame)."""
    out = {}
    for k in range(1, len(R)):
        f, tm, v = R[k]
        prev = {it[0]: it for it in R[k - 1][2][list_key]}
        now = set(it[0] for it in v[list_key])
        hx, hy = v["hero"]
        for sid, it in prev.items():
            if sid not in now and abs(it[1] - hx) <= reach_x and abs(it[2] - hy) <= reach_y:
                out[f] = out.get(f, 0) + 1
    return out


@_safe
def c_lives_vs_spikes(t):
    R = _rows(t, ["hero", "spikes", "lives"])
    vanish = _near_vanish(R, "spikes", 100, 60)
    drops = {}
    for k in range(1, len(R)):
        d = _i(R[k - 1][2]["lives"]) - _i(R[k][2]["lives"])
        if d < 0:
            return "frame %d: lives increased" % R[k][0]
        if d:
            drops[R[k][0]] = d
    if drops != vanish:
        return "life losses per frame %r != spikes destroyed next to the hero %r" % (drops, vanish)
    return None


@_safe
def c_slow_motion(t):
    R = _rows(t, ["lives", "scale", "paused"])
    hits = [k for k in range(1, len(R)) if _i(R[k][2]["lives"]) < _i(R[k - 1][2]["lives"])]
    for n, k in enumerate(hits):
        f, th, v = R[k]
        if not _near(v["scale"], 0.5, 1e-9):
            return "frame %d: scale %r at the hit" % (f, v["scale"])
        stop = hits[n + 1] if n + 1 < len(hits) else len(R)
        for j in range(k + 1, stop):
            fj, tj, vj = R[j]
            if vj["paused"]:
                break
            if tj < th + 0.25 - 1e-9 and not _near(vj["scale"], 0.5, 1e-9):
                return "frame %d: scale %r only %.4f s after hit" % (fj, vj["scale"], tj - th)
            if tj >= th + 0.25 + DT / 2 + 1e-9 and not _near(vj["scale"], 1.0, 1e-9):
                return "frame %d: scale %r %.4f s after hit (expected back to 1)" % (fj, vj["scale"], tj - th)
    return None


@_safe
def c_outro_from_lives(t):
    R = _rows(t, ["lives", "phase", "runs_ended", "clouds_scroll"])
    k0 = _first(R, lambda v: _i(v["lives"]) <= 0)
    ko = _first(R, lambda v: v["phase"] in ("outro", "done"))
    if k0 != ko:
        return "lives reached 0 at sample %r but outro began at sample %r" % (k0, ko)
    for f, tm, v in R:
        if _i(v["lives"]) < 0:
            return "frame %d: lives %r below 0" % (f, v["lives"])
        ended = v["phase"] in ("outro", "done")
        if _i(v["runs_ended"]) != (1 if ended else 0):
            return "frame %d: runs_ended %r in phase %r" % (f, v["runs_ended"], v["phase"])
        exp = (0, 0) if ended else (-40, 0)
        if not _near(v["clouds_scroll"], exp, 1e-9):
            return "frame %d: clouds scroll %r in phase %r" % (f, v["clouds_scroll"], v["phase"])
    return None


@_safe
def c_outro_reached(t):
    if any(v in ("outro", "done") for v in t.values("phase")):
        return None
    return ("assumption failed: no spike in any slot crossed (seed 7) - outro never began")


@_safe
def c_distance(t):
    R = _rows(t, ["phase", "hero", "distance"])
    kr = _first(R, lambda v: v["phase"] == "run")
    for f, tm, v in R:
        if v["phase"] in ("boot", "intro") and _i(v["distance"]) != 0:
            return "frame %d: distance %r before the run" % (f, v["distance"])
    if kr is None:
        return None
    tr = R[kr][1]
    frozen = None
    for k in range(kr, len(R)):
        f, tm, v = R[k]
        d = _i(v["distance"])
        if v["phase"] == "run":
            hi = max(0, _slot(v["hero"][0]) - 1)
            if d > hi:
                return "frame %d: distance %d ahead of hero slot (max %d)" % (f, d, hi)
            if tm >= tr + 0.5 + 2 * DT:
                tl = tm - 0.5 - 2 * DT
                xl = max(vv["hero"][0] for ff, tt, vv in R[kr:k + 1] if tt <= tl) \
                    if any(tt <= tl for ff, tt, vv in R[kr:k + 1]) else 200
                lo = max(0, _slot(xl) - 1)
                if d < lo:
                    return "frame %d: distance %d stale (at least %d)" % (f, d, lo)
        else:
            if frozen is None:
                frozen = d
            elif d != frozen:
                return "frame %d: distance changed after the run (%d -> %d)" % (f, frozen, d)
    return None


@_safe
def c_rotation(t):
    R = _rows(t, ["phase", "hero_angle"])
    ko = _first(R, lambda v: v["phase"] in ("outro", "done"))
    if ko is None:
        return "assumption failed: outro never began"
    to = R[ko][1]
    for k, (f, tm, v) in enumerate(R):
        a = v["hero_angle"]
        if k < ko:
            if not _near(a, 0, EPS):
                return "frame %d: angle %r before outro" % (f, a)
            continue
        exp = 90 * min(1.0, (tm - to) / 0.6)
        if abs(a - exp) > 3.0:
            return "frame %d: angle %.2f, expected about %.2f" % (f, a, exp)
        if tm >= to + 0.6 + 2 * DT and not _near(a, 90, EPS):
            return "frame %d: angle %.4f after the 0.6 s turn" % (f, a)
    return None


@_safe
def c_name_box_timing(t):
    R = _rows(t, ["phase", "name_vis", "name_focus", "NAME_WAIT"])
    ko = _first(R, lambda v: v["phase"] in ("outro", "done"))
    kv = _first(R, lambda v: v["name_vis"])
    kd = _first(R, lambda v: v["phase"] == "done")
    if ko is None or kv is None or kd is None:
        return "outro %r / box shown %r / done %r missing" % (ko, kv, kd)
    to, tv, td = R[ko][1], R[kv][1], R[kd][1]
    if abs(tv - (to + 0.6)) > 2 * DT + EPS:
        return "name box shown %.4f s after outro (expected 0.6)" % (tv - to)
    if not R[kv][2]["name_focus"]:
        return "name box not focused when shown"
    nw = R[0][2]["NAME_WAIT"]
    if abs(td - tv - nw) > 2 * DT + EPS:
        return "done %.4f s after the box appeared (expected %.2f)" % (td - tv, nw)
    for k, (f, tm, v) in enumerate(R):
        want = kv <= k < kd
        if v["name_vis"] != want:
            return "frame %d: name box visible=%r" % (f, v["name_vis"])
    return None


@_safe
def c_anon_result(t):
    R = _rows(t, ["phase", "result", "coins", "distance", "name_vis", "mode"])
    kd = _first(R, lambda v: v["phase"] == "done")
    if kd is None:
        return "never done"
    for f, tm, v in R[:kd]:
        if v["result"] != "":
            return "frame %d: result %r before done" % (f, v["result"])
    for f, tm, v in R[kd:]:
        exp = "ANON: %d coins, %d m" % (_i(v["coins"]), _i(v["distance"]))
        if v["result"] != exp or v["name_vis"] or v["mode"] is not None:
            return "frame %d: result %r (expected %r), box %r, mode %r" % (
                f, v["result"], exp, v["name_vis"], v["mode"])
    return None


@_safe
def c_named_result(t):
    R = _rows(t, ["phase", "result", "coins", "distance", "name_vis", "mode", "player_name"])
    fa = t.press_frame("A", 0)
    fe = t.press_frame("ENTER", 0)
    ka, ke = _frame_index(R, fa - 1), _frame_index(R, fe + 1)
    if R[ka][2]["phase"] != "outro" or not R[ka][2]["name_vis"]:
        return "assumption failed: name box not shown before typing (phase %r)" % R[ka][2]["phase"]
    v = R[ke][2]
    name = v["player_name"]
    if not isinstance(name, str) or name.upper() != "AB":
        return "player_name %r after ENTER (typed A, B)" % (name,)
    exp = "%s: %d coins, %d m" % (name, _i(v["coins"]), _i(v["distance"]))
    if v["phase"] != "done" or v["name_vis"] or v["mode"] is not None or v["result"] != exp:
        return "after ENTER: phase %r box %r mode %r result %r (expected %r)" % (
            v["phase"], v["name_vis"], v["mode"], v["result"], exp)
    for f, tm, w in R[ke:]:
        if w["result"] != exp:
            return "frame %d: result changed to %r" % (f, w["result"])
    return None


@_safe
def c_p_ignored_in_outro(t):
    R = _rows(t, ["phase", "paused"])
    fp = t.press_frame("P", 0)
    k = _frame_index(R, fp)
    if R[k][2]["phase"] != "outro":
        return "assumption failed: P arrived in phase %r, not outro" % R[k][2]["phase"]
    for f, tm, v in R[k:]:
        if v["paused"]:
            return "frame %d: clock paused by P during the outro" % f
    return None


@_safe
def c_pause_run(t):
    R = _rows(t, ["phase", "paused", "hero"])
    T = dict((f, tm) for f, tm, v in t.series("phase"))
    f1, f2 = t.press_frame("P", 0), t.press_frame("P", 1)
    k1, k2 = _frame_index(R, f1), _frame_index(R, f2)
    if R[k1][2]["phase"] != "run":
        return "assumption failed: first P in phase %r" % R[k1][2]["phase"]
    for f, tm, v in R:
        want = f1 <= f < f2
        if v["paused"] != want:
            return "frame %d: paused=%r" % (f, v["paused"])
    x1, tt1 = R[k1][2]["hero"][0], R[k1][1]
    for f, tm, v in R[k1:k2 + 1]:
        if not _near(v["hero"][0], x1, EPS) or not _near(tm, tt1, 1e-9):
            return "frame %d: world moved while paused (x %.3f, t %.5f)" % (f, v["hero"][0], tm)
    if not R[k2 + 2][2]["hero"][0] > R[k2][2]["hero"][0] + EPS:
        return "hero did not resume after the second P"
    return None


@_safe
def c_pause_intro(t):
    R = _rows(t, ["phase", "paused", "countdown", "count_text"])
    f1, f2 = t.press_frame("P", 0), t.press_frame("P", 1)
    k1, k2 = _frame_index(R, f1), _frame_index(R, f2)
    if R[k1][2]["phase"] != "intro":
        return "assumption failed: first P in phase %r" % R[k1][2]["phase"]
    c = R[k1 + 1][2]["countdown"]
    t1 = R[k1][1]
    for f, tm, v in R[k1:k2 + 1]:
        if v["phase"] != "intro":
            return "frame %d: phase %r while paused" % (f, v["phase"])
        if not _near(tm, t1, 1e-9):
            return "frame %d: clock.time advanced while paused" % f
    for f, tm, v in R[k1 + 1:k2 + 1]:
        if not _near(v["countdown"], c, 1e-9):
            return "frame %d: countdown moved while paused (%r)" % (f, v["countdown"])
    if not R[-1][2]["countdown"] < c - 0.1:
        return "countdown did not resume after the second P"
    return None


@_safe
def c_jump_arc(t):
    R = _rows(t, ["phase", "hero", "scale", "paused", "lives"])
    fj = t.press_frame("SPACE", 1)
    kj = _frame_index(R, fj)
    if R[kj - 1][2]["phase"] != "run" or not _near(R[kj - 1][2]["hero"][1], 80, EPS):
        return "assumption failed: hero not running on the ground before the jump"
    win = R[kj:kj + 49]
    if len(win) < 49:
        return "trace too short for the jump"
    for f, tm, v in win:
        if not _near(v["scale"], 1.0, 1e-12) or v["paused"] or _i(v["lives"]) != _i(R[kj - 1][2]["lives"]):
            return "assumption failed: slow motion / pause / hit during the jump (frame %d)" % f
    for n, (f, tm, v) in enumerate(win, start=1):
        if n <= 48:
            exp = 80 + (620 * n - 12.5 * n * (n + 1)) / 60.0
        else:
            exp = 80.0
        if abs(v["hero"][1] - exp) > 1e-6:
            return "jump frame %d: y %.4f, expected %.4f" % (n, v["hero"][1], exp)
    peak = max(v["hero"][1] for f, tm, v in win)
    if abs(peak - 203.0) > 1e-6:
        return "peak %.4f, expected 203.0" % peak
    return None


@_safe
def c_coins(t):
    R = _rows(t, ["hero", "coin_list", "coins", "taken"])
    vanish = _near_vanish(R, "coin_list", 80, 45)
    gains = {}
    for k in range(len(R)):
        f, tm, v = R[k]
        if _i(v["taken"]) != _i(v["coins"]):
            return "frame %d: taken has %r slots, coins %r" % (f, v["taken"], v["coins"])
        if k:
            d = _i(v["coins"]) - _i(R[k - 1][2]["coins"])
            if d < 0:
                return "frame %d: coins decreased" % f
            if d:
                gains[f] = d
    if gains != vanish:
        return "coin gains per frame %r != coins removed next to the hero %r" % (gains, vanish)
    return None


@_safe
def c_no_coins(t):
    for f, tm, v in t.series("coins"):
        if _i(v) != 0:
            return "frame %d: coins %r without a jump" % (f, v)
    return None


# -------------------------------------------------------------- scenarios ----

OUT = {"lives": 1, "speed": 3000}

SCENARIOS = {
    "idle": Scenario(params={}, seed=0, steps=[wait(600)]),
    "early_space": Scenario(params={}, seed=0, steps=[wait(39), key("SPACE"), wait(320)]),
    "skip": Scenario(params={}, seed=0, steps=[wait(99), key("SPACE"), wait(250)]),
    "jump": Scenario(params={}, seed=0, steps=[wait(99), key("SPACE"), wait(30),
                                                key("SPACE"), wait(120)]),
    "pause_run": Scenario(params={}, seed=0, steps=[wait(99), key("SPACE"), wait(20), key("P"),
                                                     wait(60), key("P"), wait(60)]),
    "pause_intro": Scenario(params={}, seed=0, steps=[wait(119), key("P"), wait(60), key("P"),
                                                       wait(40)]),
    "outro_anon": Scenario(params=dict(OUT, name_wait=1.0), seed=0,
                           steps=[wait(99), key("SPACE"), wait(320)]),
    "outro_named": Scenario(params=dict(OUT, name_wait=30.0), seed=0,
                            steps=[wait(99), key("SPACE"), wait(200), key("A"), key("B"),
                                   key("ENTER"), wait(30)]),
    "outro_p": Scenario(params=dict(OUT, name_wait=1.0), seed=0,
                        steps=[wait(99), key("SPACE"), wait(72), key("P"), wait(200)]),
}

DEFAULT_LIVES = ("idle", "early_space", "skip", "jump", "pause_run", "pause_intro")

G = "docs/pt/guide/index.html"

EXPECT = [
    Expect(id="E1", level="L0", cite="runner_story.py top-level st writes; " + G + "#frame-clock",
           text="Frame 1 (before the 0.3 s @after): phase 'boot', no mode, coins/distance/runs_ended 0, "
                "skipped False, empty name and result, countdown 3.0, name box hidden.",
           check=custom(c_start_state), scenarios=("*",)),
    Expect(id="E2", level="L0", cite="runner_story.py PARAMS.get('lives', 3)",
           text="st.lives starts at PARAMS['lives'] (3 by default, 1 in the outro scenarios).",
           check=custom(c_lives_start(3)), scenarios=DEFAULT_LIVES),
    Expect(id="E2b", level="L0", cite="runner_story.py PARAMS.get('lives', 3)",
           text="With lives=1 the run starts with one life.",
           check=custom(c_lives_start(1)), scenarios=OUTRO),
    Expect(id="E3", level="L1", cite=G + "#agendar (@after no módulo conta o tempo do jogo a partir do run())",
           text="The intro chapter begins (phase 'intro') on the first frame whose clock.time reaches 0.3 s "
                "(within one frame), with only 'boot' before it.",
           check=custom(c_intro_start), scenarios=("*",)),
    Expect(id="E4", level="L0", cite=G + "#mode-enter",
           text="Phases only advance boot -> intro -> run -> outro -> done (never back, never skipping).",
           check=custom(c_phase_order), scenarios=("*",)),
    Expect(id="E5", level="L0", cite=G + "#mode-enter (entrar roda o corpo; e.mode = None sai)",
           text="director.mode matches the phase on every frame (None/intro/running/outro/None): a mode body "
                "runs on entry in the same frame the mode is written.",
           check=custom(c_mode_matches_phase), scenarios=("*",)),
    Expect(id="E6", level="L1", cite=G + "#mover-tween (ease padrão 'linear'); #mode-async parallel",
           text="During the first 0.8 s of the intro the hint rises linearly from y=-40 to 360 at x=500 "
                "(tolerance 9.5 = one frame of travel + slop for the start frame).",
           check=custom(c_hint_linear), scenarios=("*",)),
    Expect(id="E7", level="L1", cite=G + "#mover-tween; runner_story.py intro",
           text="Title/hint sit at (500,700)/(500,-40) before the intro, end at (500,420)/(500,360) after "
                "0.8 s, are visible through the intro and hidden from the run on.",
           check=custom(c_title_hint_end), scenarios=("*",)),
    Expect(id="E8", level="L1", cite=G + "#mover-tween ease=; #util-remap (ease_out)",
           text="ease_out moves the title monotonically down and never behind the linear schedule "
                "(assumed: ease_out progress >= linear progress at every u).",
           check=custom(c_title_ease_out), scenarios=("*",), guess=True),
    Expect(id="E9", level="L1", cite=G + "#mover-tween (linear) on st['countdown']",
           text="The countdown tween runs 3.0 -> 0.0 linearly over 3 s starting when the 0.8 s title tweens "
                "end (tolerance 0.05 s ~ 3 frames of start lag).",
           check=custom(c_countdown_linear), scenarios=("idle", "early_space", "skip", "jump", "pause_run",
                                                        "outro_anon", "outro_named", "outro_p")),
    Expect(id="E10", level="L0", cite=G + "#reativo (@= pull: always current)",
           text="count_text shows f'{countdown:.1f}' exactly while the phase is 'intro' and '' otherwise.",
           check=custom(c_count_text), scenarios=("*",)),
    Expect(id="E11", level="L1", cite=G + "#mode-async (await handle); #mode-enter",
           text="Without a skip, the run starts 3.8 s (0.8 + 3.0) after the intro began, with countdown "
                "exactly 0, skipped never True, and title/hint hidden.",
           check=custom(c_run_start_unskipped), scenarios=("idle", "early_space")),
    Expect(id="E12", level="L0", cite=G + "#frame-teclado (keyp.once: a primeira leitura gasta o aperto)",
           text="SPACE pressed before the countdown handle exists (during the title tween) does nothing: "
                "the intro continues and skipped stays False.",
           check=custom(c_early_space_ignored), scenarios=("early_space",)),
    Expect(id="E13", level="L0", cite=G + "#mode-async (Handle cancelado levanta Cancelled); #frame-teclado",
           text="SPACE during the countdown cancels it: from the next frame skipped is True, phase is 'run' "
                "and title/hint are hidden.",
           check=custom(c_skip), scenarios=SKIPPED),
    Expect(id="E14", level="L1", cite=G + "#mode-async (.cancel 'Para agora')",
           text="A cancelled countdown keeps the value it had at the skip (about 3 - elapsed, in (0,3)) and "
                "never moves again.",
           check=custom(c_skip_countdown_frozen), scenarios=SKIPPED),
    Expect(id="E15", level="L1", cite=G + "#frame-teclado (keyp.once spent by the skip read)",
           text="Without a second SPACE the hero never leaves y=80 (the skip SPACE is spent in the intro "
                "branch and cannot also jump).",
           check=custom(c_hero_on_ground), scenarios=NO_JUMP),
    Expect(id="E16", level="L0", cite="runner_story.py update (hero moves only while running)",
           text="Before the run the hero stays at (200,80) with angle 0.",
           check=custom(c_hero_still_before_run), scenarios=("*",)),
    Expect(id="E17", level="L1", cite=G + "#frame-clock (dt em escala do jogo; 0 pausado)",
           text="Between consecutive running frames the hero advances exactly SPEED * (world dt), so slow "
                "motion halves and pause stops it; after the run it never moves.",
           check=custom(c_run_motion), scenarios=("*",)),
    Expect(id="E18", revised="NUMERIC: game_view is float32 camera math, ~1e-5 off pan_x; tolerance 1e-3", level="L1", cite=G + "#mundo-camera (canvas.pan_x/pan_y; game_view)",
           text="While running the camera centre is (hero.x + 300, initial pan_y); game_view is centred on "
                "pan_x; haze sits at (view centre x, 30) every frame; the camera stays put after the run.",
           check=custom(c_camera), scenarios=("*",)),
    Expect(id="E19", level="L1", cite=G + "#mundo-camera (pan = centro da janela)",
           text="At rest the camera centre is the design centre (500,300) and game_view is [0,1000]x[0,600] "
                "(assumed: the initial view is the design rectangle).",
           check=custom(c_camera_rest), scenarios=("*",), guess=True),
    Expect(id="E20", revised="SPEC-LOGIC: the phase flips after update() in the transition frame; check from the second run frame", level="L1", cite=G + "#colocar-pais (canvas.playfield.set(box))",
           text="While running the playfield equals game_view outset by 60 on every side.",
           check=custom(c_playfield), scenarios=("*",)),
    Expect(id="E21", level="L1", cite="runner_story.py update (dust follows every frame)",
           text="dust.center == (hero.x, 64) on every frame.",
           check=custom(c_dust), scenarios=("*",)),
    Expect(id="E22", level="L1", cite=G + "#som-audio (amp_db em 0..1)",
           text="The meter's height stays in [4, 104] and its bottom edge stays at y=20 (x=970).",
           check=custom(c_meter), scenarios=("*",)),
    Expect(id="E23", level="L0", cite=G + "#reativo (Text text @= lambda)",
           text="hud.text == 'Lives {lives}  Coins {coins}  Dist {distance}' on every frame.",
           check=custom(c_hud), scenarios=("*",)),
    Expect(id="E24", level="L0", cite=G + "#mundo-camadas (below/above: z do alvo -/+ 1; layer padrão default)",
           text="Layer order: track z=-1, clouds z=-2, dust on layer 1, haze on layer -3, hero on 'default', "
                "title on 'ui'.",
           check=custom(c_layers), scenarios=("*",)),
    Expect(id="E25", level="L0", cite="design/Canvas Design.md#endless-fill (builder runs on the Endless layer)",
           text="Every live track piece is on layer 'track', every cloud on 'clouds', and the sky always has "
                "at least one cloud.",
           check=custom(c_piece_layers), scenarios=("*",)),
    Expect(id="E26", level="L0", cite=G + "#mundo-sem-fim (Endless enche a parte que a câmera mostra)",
           text="Every ground piece is 300x60 centred at y=30, and some ground piece always spans the hero's x.",
           check=custom(c_ground_under_hero), scenarios=("*",)),
    Expect(id="E27", level="L2", cite="design/Canvas Design.md#endless-fill (Fill rule: ahead 0.5, behind 1.0 view)",
           text="Live ground pieces number 7..11: the 2000-wide build window always overlaps >= 7 slots of "
                "300 and the 3000-wide keep window holds at most 11.",
           check=custom(c_ground_count), scenarios=("*",)),
    Expect(id="E28", level="L0", cite=G + "#mundo-sem-fim (start: borda da tela; slot.i, slot.left)",
           text="Slots start at x=0 (assumed: 'a borda da tela' is the left edge, view [0,1000]): ground at "
                "300i+150, spikes at 300i+150 (i>=2, y=85), coins at y=190 inside [left+40, left+260] of a "
                "slot i>=1 with coin.stretch == i.",
           check=custom(c_slot_alignment), scenarios=("*",), guess=True),
    Expect(id="E29", level="L0", cite=G + "#desenhar (set_defaults: vale até a próxima chamada)",
           text="Ground built in the Endless constructor (first screen) is dim gray; ground built later during "
                "play is orange, because set_defaults('orange', line_width=2.0) is then the current default; "
                "the hero is orange with line_width 2.0.",
           check=custom(c_colors), scenarios=("*",)),
    Expect(id="E30", level="L2", cite="design/Scena Design.md#collision; " + G + "#mundo-sem-fim",
           text="No live spike ever overlaps a hero that is low enough to touch it (|dx| < 34.5 with "
                "hero.y < 129.5): the hit handler destroys it in the frame of contact.",
           check=custom(c_no_spike_overlap), scenarios=("*",)),
    Expect(id="E31", level="L0", cite="design/Scena Design.md#frame-order (collision step 4)",
           text="Lives never increase, and each life lost coincides frame-for-frame with a spike removed next "
                "to the hero (Endless only releases slots a view behind).",
           check=custom(c_lives_vs_spikes), scenarios=("*",)),
    Expect(id="E32", level="L1", cite=G + "#frame-clock (scale 0.5 câmera lenta); #agendar (after)",
           text="A hit sets clock.scale to 0.5, and it returns to 1.0 once 0.25 s of world time has passed "
                "(checked until the next hit or a pause).",
           check=custom(c_slow_motion), scenarios=NO_PAUSE),
    Expect(id="E33", level="L0", cite=G + "#mode-enter (@exit_mode); #mundo-camadas (.scroll)",
           text="The outro begins in exactly the frame lives reach 0; runs_ended is 1 from then on (0 before), "
                "the clouds layer scroll is (-40,0) before and (0,0) after, and lives never go below 0.",
           check=custom(c_outro_from_lives), scenarios=("*",)),
    Expect(id="E34", level="L0", cite="runner_story.py stretch() with seed 7",
           text="At speed 3000 with one life the hero hits a spike and the outro begins (assumption: seed 7 "
                "puts a spike in some slot 2..12; each has chance 0.6).",
           check=custom(c_outro_reached), scenarios=OUTRO),
    Expect(id="E35", level="L1", cite=G + "#mundo-sem-fim (index_at); " + G + "#mode-cancela (every no mode)",
           text="distance is 0 before the run; while running it is max(0, slot(hero.x)-1) sampled at most "
                "~0.5 s ago (slots from x=0 assumed); it freezes once the run ends (every is mode-scoped).",
           check=custom(c_distance), scenarios=("*",), guess=True),
    Expect(id="E36", level="L1", cite=G + "#mover-pose (rotate_by: como escrito; time=)",
           text="The hero's angle is 0 until the outro, then turns linearly to 90 degrees over 0.6 s of world "
                "time (tolerance 3 degrees) and stays at 90.",
           check=custom(c_rotation), scenarios=OUTRO),
    Expect(id="E37", level="L1", cite=G + "#ui-textinput (.focus, .focused); #mode-async (race, wait)",
           text="The name box appears focused 0.6 s (world) after the outro begins, stays visible for "
                "name_wait seconds, then hides as the phase becomes 'done'.",
           check=custom(c_name_box_timing), scenarios=("outro_anon",)),
    Expect(id="E38", level="L0", cite=G + "#mode-async (race: índice do primeiro)",
           text="With nobody typing, the wait wins the race: result becomes 'ANON: {coins} coins, {distance} m' "
                "at 'done' (empty before), the box is hidden and the director's mode is None.",
           check=custom(c_anon_result), scenarios=("outro_anon",)),
    Expect(id="E39", level="L0", cite=G + "#ui-textinput (Enter grava no Attribute, depois on_submit(valor))",
           text="Typing A, B, ENTER into the focused box writes 'AB' to st.player_name, on_submit sets result "
                "to 'AB: {coins} coins, {distance} m', the until wins the race and the story ends (box hidden, "
                "mode None) within a frame (assumed: key() steps produce typed characters; case not checked).",
           check=custom(c_named_result), scenarios=("outro_named",), guess=True),
    Expect(id="E40", level="L0", cite="runner_story.py update (P ignored in outro)",
           text="P pressed during the outro does not pause the clock.",
           check=custom(c_p_ignored_in_outro), scenarios=("outro_p",)),
    Expect(id="E41", level="L0", cite=G + "#frame-clock (paused: scale 0; dt 0)",
           text="P while running pauses the world: paused is True until the second P, hero.x and clock.time "
                "do not change from the first P frame to the second, and the hero moves again afterwards.",
           check=custom(c_pause_run), scenarios=("pause_run",)),
    Expect(id="E42", level="L0", cite=G + "#frame-clock; " + G + "#mover-tween",
           text="P during the countdown freezes clock.time and the countdown tween (phase stays 'intro'); the "
                "second P resumes it.",
           check=custom(c_pause_intro), scenarios=("pause_intro",)),
    Expect(id="E43", level="L1", cite="runner_story.py update (semi-implicit jump); " + G + "#frame-clock",
           text="A SPACE while running on the ground gives the closed-form arc y_n = 80 + (620n - 12.5n(n+1))/60 "
                "for 48 frames (peak 203.0 at n=24) and lands at y=80 on frame 49 (assumes dt=1/60, scale 1, "
                "no hit during the jump; the check verifies that).",
           check=custom(c_jump_arc), scenarios=("jump",)),
    Expect(id="E44", level="L0", cite=G + "#mundo-sem-fim (Guardar o que mudou: set por slot.i)",
           text="Coins never decrease, len(taken) == coins on every frame, and each coin gained coincides "
                "with a coin removed next to the hero.",
           check=custom(c_coins), scenarios=("*",)),
    Expect(id="E45", level="L0", cite="runner_story.py (coins at y 180..200, standing hero spans y 60..100)",
           text="A hero that never jumps never collects a coin.",
           check=custom(c_no_coins), scenarios=NO_JUMP),
]
