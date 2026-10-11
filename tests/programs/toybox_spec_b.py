"""Spec B for tests/programs/toybox.py — pointer interaction first.

Written from the docs only (see FILES_READ); the engine never ran while it was
written. Most scenarios use count=1, speed=0 and seed=0 so the single toy stands
still where the program's own spawn() puts it.

Spawn assumption (guess, checked by E01): random is seeded with 0 just before
the script runs and nothing else draws from `random` before spawn(), so the
toy's centre is (80 + 840 r1, 400 + 180 r2) = (789.3144, 536.4318), its heading
uniform(0, 360) = 151.41 deg, and the first drop into a bin puts it at
bin.x + uniform(-70, 70) = bin.x - 33.7517.
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, drag, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "tests/programs/toybox.py",
    "design/Scena Design.md#frame-order",
    "design/Shapes Design.md#pointer-interaction-click--drag--drop",
    "design/Shapes Design.md#drag-and-drop",
    "design/Shapes Design.md#hover-pointer_hover-hover--hover_exit",
    "design/Collision Design.md (touching_contacts / side, lines ~455-481)",
    "docs/pt/guide/index.html#reagir-pointer",
    "docs/pt/guide/index.html#ptr-drag",
    "docs/pt/guide/index.html#ptr-hover",
    "docs/pt/guide/index.html (Decorators table, Em todo Graphic: pointer_pressed)",
    "docs/pt/guide/index.html (@when / @on_change contract: flush, unregister_event)",
    "docs/pt/guide/index.html#colisao-collide (enter / stay / exit table)",
    "docs/pt/guide/index.html (collision.resolve_enabled, test_collision)",
    "docs/pt/guide/index.html (above / below)",
    "docs/pt/guide/index.html (Color: .rgb; Shape .color)",
    "docs/pt/guide/index.html (Grupos: group[...].index)",
]

# -- spawn facts (see module docstring) -------------------------------------
X0, Y0 = 789.3143552810404, 536.4317925292544
BIN_U = -33.75165495898513          # first uniform(-70, 70) after spawn
RED_X = 200 + BIN_U                 # 166.248...
BLUE_X = 800 + BIN_U
DT = 1 / 60
STILL = {"count": 1, "speed": 0}


# -- probe helpers ----------------------------------------------------------
def _toy0(p):
    return list(p.group["toy"])[0]


def _xy(pt):
    return (float(pt.x), float(pt.y))


def _rgb_is(p, obj, name):
    a = tuple(obj.color.rgb)
    b = tuple(p.Color(name).rgb)
    return all(abs(x - y) < 1e-6 for x, y in zip(a, b))


def _toys_box(p):
    xs = [float(t.center.x) for t in p.group["toy"]]
    ys = [float(t.center.y) for t in p.group["toy"]]
    return (min(xs), max(xs), min(ys), max(ys))


def _min_pair_dist(p):
    cs = [_xy(t.center) for t in p.group["toy"]]
    best = 1e9
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            best = min(best, math.hypot(cs[i][0] - cs[j][0], cs[i][1] - cs[j][1]))
    return best


PROBES = {
    "toy0": lambda p: _xy(_toy0(p).center),
    "toy0_vel": lambda p: _xy(_toy0(p).vel),
    "toy0_loose": lambda p: _toy0(p).tagged("loose"),
    "toy0_red": lambda p: _toy0(p).tagged("red"),
    "toy0_blue": lambda p: _toy0(p).tagged("blue"),
    "toy0_pressed": lambda p: _toy0(p).pointer_pressed,
    "toy0_hover": lambda p: _toy0(p).pointer_hover,
    "toy0_gold": lambda p: _rgb_is(p, _toy0(p), "gold"),
    "toy0_coral": lambda p: _rgb_is(p, _toy0(p), "coral"),
    "n_toy": lambda p: len(list(p.group["toy"])),
    "n_loose": lambda p: len(list(p.group["loose"])),
    "toys_box": _toys_box,
    "min_pair": _min_pair_dist,
    "energy": lambda p: sum(float(t.vel.x) ** 2 + float(t.vel.y) ** 2 for t in p.group["toy"]),
    "ring_visible": lambda p: bool(p.ring.visible),
    "ring_center": lambda p: _xy(p.ring.center),
    "layers": lambda p: (p.red_bin.layer == p.below("default"),
                         p.blue_bin.layer == p.below("default"),
                         p.ring.layer == p.above("default")),
    "resolve_enabled": lambda p: bool(p.collision.resolve_enabled),
    "status": lambda p: str(p.status.text),
    "binned": lambda p: p.st.binned,
    "changes": lambda p: p.st.changes,
    "flushed": lambda p: bool(p.st.flushed),
    "watching": lambda p: bool(p.st.watching),
    "hovers": lambda p: p.st.hovers,
    "hover_exits": lambda p: p.st.hover_exits,
    "hovered": lambda p: str(p.st.hovered),
    "over_frames": lambda p: p.st.over_frames,
    "over_target": lambda p: str(p.st.over_target),
    "drops": lambda p: p.st.drops,
    "misses": lambda p: p.st.misses,
    "bumps": lambda p: p.st.bumps,
    "bump_point": lambda p: tuple(p.st.bump_point),
    "pad_frames": lambda p: p.st.pad_frames,
    "pad_exits": lambda p: p.st.pad_exits,
    "glue_frames": lambda p: p.st.glue_frames,
    "glue_exits": lambda p: p.st.glue_exits,
    "wall_side": lambda p: str(p.st.wall_side),
    "scanned": lambda p: p.st.scanned,
    "solid": lambda p: bool(p.st.solid),
    "in_red": lambda p: p.st.in_red,
    "in_blue": lambda p: p.st.in_blue,
}


# -- frame helpers ----------------------------------------------------------
def rel(n, k=0):
    """Frame of the nth left release, plus k."""
    return lambda t: t.release_frame("left", n) + k


def keyf(name, n=0, k=0):
    return lambda t: t.press_frame(name, n) + k


def eq(v):
    return lambda x: x == v


def near(pt, tol):
    return lambda x: close(x, pt, tol)


SCENARIOS = {
    # nothing pressed, one still toy
    "still": Scenario(params=STILL, seed=0, steps=[wait(60)]),
    # nothing pressed, six moving toys
    "idle_moving": Scenario(params={"count": 6, "speed": 160}, seed=0, steps=[wait(300)]),
    # hover enter / exit / enter
    "hover": Scenario(params=STILL, seed=0, steps=[
        wait(2), move(X0, Y0), wait(3), move(500, 200), wait(3), move(X0, Y0), wait(3)]),
    # two drops on empty floor
    "floor_drop": Scenario(params=STILL, seed=0, steps=[
        wait(2), drag(X0, Y0, 600, 250, 10), wait(10),
        drag(600, 250, 300, 450, 10), wait(10)]),
    # drop on the pad (crossing the bumper), dwell, drag away
    "pad": Scenario(params=STILL, seed=0, steps=[
        wait(2), drag(X0, Y0, 220, 500, 10), wait(30),
        drag(220, 500, 600, 250, 10), wait(20)]),
    # red bin drop, re-drag the binned toy onto blue, SPACE tips it out
    "red_drop": Scenario(params=STILL, seed=0, steps=[
        wait(2), drag(X0, Y0, 200, 90, 10), wait(10),
        drag(RED_X, 90, 800, 90, 10), wait(10),
        key("SPACE"), wait(5)]),
    # blue bin drop (crosses the glue strip on the way)
    "blue_drop": Scenario(params=STILL, seed=0, steps=[
        wait(2), drag(X0, Y0, 800, 90, 10), wait(10)]),
    # U first: the watcher is gone, then a drop and SPACE
    "unwatched": Scenario(params=STILL, seed=0, steps=[
        wait(2), key("U"), wait(2), drag(X0, Y0, 200, 90, 10), wait(5),
        key("SPACE"), wait(5)]),
    # scanner: empty, toy dropped on it, toy taken away
    "scanner": Scenario(params=STILL, seed=0, steps=[
        wait(2), click(860, 615), wait(2),
        drag(X0, Y0, 910, 640, 10), wait(5), click(860, 615), wait(3),
        drag(910, 640, 500, 200, 10), wait(5), click(860, 615), wait(3)]),
    # R / P / U / SPACE toggles with nothing binned
    "keys": Scenario(params={"count": 3, "speed": 160}, seed=0, steps=[
        wait(5), key("R"), wait(5), key("P"), wait(5), key("R"), wait(5),
        key("P"), wait(5), key("U"), wait(5), key("U"), wait(5),
        key("SPACE"), wait(5)]),
    # grab a moving toy on frame 1: held, it stops drifting; dropped, it drifts again
    "drag_moving": Scenario(params={"count": 1, "speed": 160}, seed=0, steps=[
        drag(X0, Y0, 600, 250, 10), wait(30)]),
}


# -- custom checks ----------------------------------------------------------
def hover_balanced(t):
    for f, _, h in t.series("hovers"):
        e = t.at_frame(f, "hover_exits")
        name = t.at_frame(f, "hovered")
        d = h - e
        if d not in (0, 1):
            return f"frame {f}: hovers {h} vs exits {e}"
        if (name != "") != (d == 1):
            return f"frame {f}: hovered {name!r} with hovers-exits {d}"
    return True


def ledger_consistent(t):
    for f, _, n in t.series("n_toy"):
        r, b, l = t.at_frame(f, "in_red"), t.at_frame(f, "in_blue"), t.at_frame(f, "n_loose")
        if r + b + l != n:
            return f"frame {f}: red {r} + blue {b} + loose {l} != {n}"
        if t.at_frame(f, "binned") != r + b:
            return f"frame {f}: binned {t.at_frame(f, 'binned')} != red+blue {r + b}"
    return True


def spawn_assumption(t):
    c = t.at_frame(1, "toy0")
    if not close(c, (X0, Y0), 0.01):
        return f"spawn assumption failed: toy0 at {c}, expected {(X0, Y0)}"
    return True


def pressed_while_dragging(n):
    def fn(t):
        a, b = t.press_frame("left", n), t.release_frame("left", n)
        for f in range(a, b):
            if t.at_frame(f, "toy0_pressed") is not True:
                return f"frame {f}: pointer_pressed not True during the drag"
        if t.at_frame(b, "toy0_pressed") is not False:
            return f"frame {b}: pointer_pressed still True after release"
        return True
    return fn


def over_count(n, frames):
    def fn(t):
        before = t.at_frame(t.press_frame("left", n) - 1, "over_frames")
        after = t.at_frame(rel(n, 2)(t), "over_frames")
        d = after - before
        if not (frames - 1 <= d <= frames):
            return f"drag_over fired {d} times over a {frames}-move drag"
        return True
    return fn


def red_landing(t):
    f = rel(0, 5)(t)
    x, y = t.at_frame(f, "toy0")
    if not (130 - 1e-6 <= x <= 270 + 1e-6 and abs(y - 90) < 1e-6):
        return f"toy at {(x, y)} not on the red bin line y=90, x in [130, 270]"
    return True


def red_landing_assumption(t):
    x, _ = t.at_frame(rel(0, 5)(t), "toy0")
    if abs(x - RED_X) > 0.01:
        return f"random assumption failed: landed x {x}, expected {RED_X}"
    return True


def red_hover_left(t):
    f = rel(0, 5)(t)
    x, y = t.at_frame(f, "toy0")
    if math.hypot(x - 200, y - 90) <= 22:
        return "assumption failed: toy landed under the cursor"
    if t.at_frame(f, "hovered") != "":
        return f"hovered {t.at_frame(f, 'hovered')!r} after the toy left the cursor"
    if t.at_frame(f, "toy0_coral") is not True:
        return "toy not back to coral after hover_exit"
    return True


def space_reloose(t):
    f = keyf("SPACE", 0, 2)(t)
    x, y = t.at_frame(f, "toy0")
    if not (80 <= x <= 920 and 420 <= y <= 580):
        return f"after SPACE toy at {(x, y)}, outside [80,920]x[420,580]"
    return True


def pad_dwell(t):
    a = rel(0, 5)(t)
    b = rel(0, 25)(t)
    d = t.at_frame(b, "pad_frames") - t.at_frame(a, "pad_frames")
    if d != 20:
        return f"pad_frames grew by {d} over 20 resting frames"
    return True


def pad_quiet_after_leave(t):
    a = rel(1, 3)(t)
    v = t.at_frame(a, "pad_frames")
    for f, _, x in t.series("pad_frames"):
        if f >= a and x != v:
            return f"frame {f}: pad_frames {x} kept growing after the toy left (was {v})"
    return True


def bin_y_untouched_by_drag(t):
    # landed() put the toy at y=90 exactly; it stays still (vel 0, not loose)
    a, b = rel(0, 2)(t), rel(0, 10)(t)
    for f in range(a, b + 1):
        if not close(t.at_frame(f, "toy0"), t.at_frame(a, "toy0"), 1e-6):
            return f"binned toy moved at frame {f}"
    return True


def moving_held(t):
    a = t.press_frame("left", 0)
    if not close(t.at_frame(a, "toy0"), (X0, Y0), 0.01):
        return f"held toy drifted on the press frame: {t.at_frame(a, 'toy0')}"
    return True


def moving_released(t):
    r = t.release_frame("left", 0)
    step = 160 * DT
    if not close(t.at_frame(r, "toy0"), (600, 250), step + 0.5):
        return f"release frame: toy at {t.at_frame(r, 'toy0')}, not ~(600, 250)"
    x, y = t.at_frame(r + 30, "toy0")
    d = math.hypot(x - 600, y - 250)
    if not (40 <= d <= 31 * step + 0.5):
        return f"after 30 more frames toy moved {d:.1f} from the drop point"
    return True


def walls_hold(t):
    lo, hi_x, hi_y, slop = 42, 958, 658, 8
    for f, _, (x0, x1, y0, y1) in t.series("toys_box"):
        if x0 < lo - slop or x1 > hi_x + slop or y0 < lo - slop or y1 > hi_y + slop:
            return f"frame {f}: a toy left the walls {(x0, x1, y0, y1)}"
    return True


EXPECT = [
    # ---- startup / nothing pressed ---------------------------------------
    Expect(id="E01", level="L0", cite="tests/programs/toybox.py spawn(); harness: random seeded",
           text="Guess: with seed 0, count 1, speed 0 the toy spawns at (789.31, 536.43) (no other random draw precedes spawn).",
           check=custom(spawn_assumption), scenarios=("still", "hover", "floor_drop", "pad", "red_drop",
                                                     "blue_drop", "unwatched", "scanner"), guess=True),
    Expect(id="E02", level="L0", cite="tests/programs/toybox.py update(); speed=0",
           text="With speed 0 and no input the toy never moves.",
           check=steady("toy0", after=1, tol=1e-9), scenarios=("still",)),
    Expect(id="E03", level="L0", cite="tests/programs/toybox.py st initial values",
           text="With nothing pressed every counter stays at its start value and the toy stays loose.",
           check=all_of(*[always(pr, eq(0)) for pr in ("drops", "misses", "binned", "changes", "scanned",
                                                     "bumps", "pad_frames", "glue_frames", "over_frames")],
                        always("toy0_loose", eq(True)), always("flushed", eq(True)),
                        always("solid", eq(True)), always("watching", eq(True)),
                        always("ring_visible", eq(False)), always("resolve_enabled", eq(True))),
           scenarios=("still",)),
    Expect(id="E04", level="L0", cite="docs/pt/guide/index.html (above / below table)",
           text="Bins sit on below('default') and the ring on above('default').",
           check=at_end("layers", eq((True, True, True))), scenarios=("still",)),
    Expect(id="E05", level="L0", cite="design/Shapes Design.md#hover — entries wait for pointer motion",
           text="Guess: with no pointer input the cursor starts off every toy, so no hover ever fires.",
           check=all_of(always("hovers", eq(0)), always("hover_exits", eq(0))),
           scenarios=("still", "idle_moving", "keys"), guess=True),
    Expect(id="E06", level="L0", cite="docs/pt/guide/index.html Text / @= formula; toybox.py status",
           text="The status line reads the cells: 'bins 0  red 0  blue 0  drops 0  misses 0' and 'solid' at rest.",
           check=at_end("status", lambda s: s.startswith("bins 0  red 0  blue 0  drops 0  misses 0") and " solid " in s),
           scenarios=("still",)),
    Expect(id="E07", level="L0", cite="tests/programs/toybox.py spawn(), group tags",
           text="Six toys exist all run long, all tagged loose, none binned, nothing dropped.",
           check=all_of(always("n_toy", eq(6)), always("n_loose", eq(6)), always("binned", eq(0)),
                        always("drops", eq(0)), always("misses", eq(0)), always("changes", eq(0)),
                        always("ring_visible", eq(False))),
           scenarios=("idle_moving",)),
    Expect(id="E08", level="L2", cite="docs/pt/guide/index.html#colisao-resolve; resolve('toy','wall')",
           text="Toys (r=22) stay inside the 20-px walls: centre in [42, 958]x[42, 658], slop 8 px (one frame's travel at up to ~2x speed plus solver tolerance).",
           check=custom(walls_hold), scenarios=("idle_moving",)),
    Expect(id="E09", level="L2", cite="docs/pt/guide/index.html#colisao-resolve (bounce=1.0); toybox.py glue / bumper",
           text="Total toy kinetic energy never exceeds its start (6 x 160^2) by more than 1%: walls and toy pairs bounce elastically, the bumper reflects, glue only slows.",
           check=always("energy", lambda e: e <= 6 * 160 ** 2 * 1.01), scenarios=("idle_moving",), guess=True),
    Expect(id="E10", level="L2", cite="docs/pt/guide/index.html#colisao-resolve; resolve('toy','toy')",
           text="After frame 5 solid toys (r=22) never sink deeper than 6 px into each other (centres >= 38 px apart).",
           check=always("min_pair", lambda d: d >= 38, after=5), scenarios=("idle_moving",)),
    Expect(id="E11", level="L0", cite="design/Collision Design.md (touching_contacts side vocabulary)",
           text="Guess: wall_side is only ever '', 'left', 'right', 'top' or 'bottom'.",
           check=always("wall_side", lambda s: s in ("", "left", "right", "top", "bottom")),
           scenarios=("idle_moving",), guess=True),

    # ---- invariants over every scenario ---------------------------------
    Expect(id="E12", level="L0", cite="design/Shapes Design.md#hover — every enter is followed by exactly one exit",
           text="hovers - hover_exits is always 0 or 1, and st.hovered is non-empty exactly when it is 1.",
           check=custom(hover_balanced), scenarios=("*",)),
    Expect(id="E13", level="L0", cite="tests/programs/toybox.py landed / on_key_down SPACE / update",
           text="Every toy is in exactly one of loose / red / blue, and st.binned equals in_red + in_blue on every frame.",
           check=custom(ledger_consistent), scenarios=("*",)),
    Expect(id="E14", level="L0", cite="docs/pt/guide/index.html (@on_change contract: flush() runs pending checks now)",
           text="flush() inside the drop runs the on_change watcher at once, so st.flushed is never cleared.",
           check=always("flushed", eq(True)), scenarios=("*",)),
    Expect(id="E15", level="L0", cite="design/Shapes Design.md#drag-and-drop step 4; toybox.py let_go",
           text="With the button up at the end, the held-toy ring is hidden (drag_to hides it on every release).",
           check=at_end("ring_visible", eq(False)), scenarios=("*",)),

    # ---- hover ---------------------------------------------------------------
    Expect(id="E16", level="L0", cite="docs/pt/guide/index.html#ptr-hover; Shapes Design Hover",
           text="Moving onto the toy fires @hover once: hovered 'toy0', pointer_hover True, colour gold.",
           check=all_of(at(lambda t: t.input_frame("move", 0) + 2, "hovers", eq(1)),
                        at(lambda t: t.input_frame("move", 0) + 2, "hovered", eq("toy0")),
                        at(lambda t: t.input_frame("move", 0) + 2, "toy0_hover", eq(True)),
                        at(lambda t: t.input_frame("move", 0) + 2, "toy0_gold", eq(True))),
           scenarios=("hover",)),
    Expect(id="E17", level="L0", cite="design/Shapes Design.md#hover — exits are immediate",
           text="Moving off the toy fires @hover_exit once: hovered '', pointer_hover False, colour back to coral.",
           check=all_of(at(lambda t: t.input_frame("move", 1) + 2, "hover_exits", eq(1)),
                        at(lambda t: t.input_frame("move", 1) + 2, "hovered", eq("")),
                        at(lambda t: t.input_frame("move", 1) + 2, "toy0_hover", eq(False)),
                        at(lambda t: t.input_frame("move", 1) + 2, "toy0_coral", eq(True))),
           scenarios=("hover",)),
    Expect(id="E18", level="L0", cite="docs/pt/guide/index.html#ptr-hover",
           text="Coming back fires a second @hover: 2 hovers, 1 exit, toy gold at the end.",
           check=all_of(at_end("hovers", eq(2)), at_end("hover_exits", eq(1)), at_end("toy0_gold", eq(True))),
           scenarios=("hover",)),
    Expect(id="E19", level="L0", cite="design/Shapes Design.md#hover — a hover-only/draggable target is not a press",
           text="Hovering is not a press or a drag: no drag_over, no drop, no miss, toy never pointer_pressed.",
           check=all_of(always("over_frames", eq(0)), always("misses", eq(0)), always("drops", eq(0)),
                        always("toy0_pressed", eq(False))),
           scenarios=("hover",)),

    # ---- drag / drop on the floor ------------------------------------------
    Expect(id="E20", level="L0", cite="docs/pt/guide/index.html (pointer_pressed: arrastando fica True)",
           text="pointer_pressed is True on the dragged toy from the press until the release frame, then False.",
           check=all_of(custom(pressed_while_dragging(0)), custom(pressed_while_dragging(1))),
           scenarios=("floor_drop", "pad")),
    Expect(id="E21", level="L0", cite="design/Shapes Design.md#drag-and-drop (drag_over each move, to may be None); toybox.py let_go",
           text="A floor drop: drag_to gets target None, so misses counts 1 per drop, drops stay 0, the toy stays loose; over_target is ''.",
           check=all_of(at(rel(0, 2), "misses", eq(1)), at_end("misses", eq(2)), always("drops", eq(0)),
                        always("toy0_loose", eq(True)), at_end("over_target", eq(""))),
           scenarios=("floor_drop",)),
    Expect(id="E22", level="L1", cite="docs/pt/guide/index.html#ptr-drag (pos = where it was released); toybox.py let_go",
           text="A floor drop puts the toy exactly at the release point: (600, 250), then (300, 450).",
           check=all_of(at(rel(0, 2), "toy0", near((600, 250), 1e-6)), at_end("toy0", near((300, 450), 1e-6))),
           scenarios=("floor_drop",)),
    Expect(id="E23", level="L1", cite="design/Shapes Design.md#drag-and-drop (drag_over pos = pointer)",
           text="The ring follows the last drag_over pos, so after each drag it sits at the drop point.",
           check=all_of(at(rel(0, 2), "ring_center", near((600, 250), 1e-6)),
                        at_end("ring_center", near((300, 450), 1e-6))),
           scenarios=("floor_drop",)),
    Expect(id="E24", level="L0", cite="design/Shapes Design.md#drag-and-drop — 'each move during a drag calls on_drag_over'",
           text="Guess: a 10-move drag fires drag_over 9 or 10 times (the crossing move may only start the drag); the ring is visible during it.",
           check=all_of(custom(over_count(0, 10)), custom(over_count(1, 10)),
                        at(rel(0, -1), "ring_visible", eq(True))),
           scenarios=("floor_drop",), guess=True),
    Expect(id="E25", level="L0", cite="design/Shapes Design.md#hover — a pressed or dragged Graphic keeps hover",
           text="Guess: after a floor drop the toy sits under the still cursor, so it is still the hover target ('toy0').",
           check=at_end("hovered", eq("toy0")), scenarios=("floor_drop",), guess=True),

    # ---- pad / bumper -------------------------------------------------------
    Expect(id="E26", level="L0", cite="docs/pt/guide/index.html#colisao-collide (stay: each following frame still overlapping)",
           text="A toy resting on the pad fires collide_stay every frame: +20 over 20 frames.",
           check=custom(pad_dwell), scenarios=("pad",)),
    Expect(id="E27", level="L0", cite="docs/pt/guide/index.html#colisao-collide (exit)",
           text="Dragging the toy off the pad fires collide_exit once; then pad_frames stops growing.",
           check=all_of(at_end("pad_exits", eq(1)), custom(pad_quiet_after_leave)),
           scenarios=("pad",)),
    Expect(id="E28", level="L0", cite="docs/pt/guide/index.html (Colocar x viajar: placed objects checked where they stop); @collide(bumper, ANYTHING)",
           text="Guess: the drag path crosses the bumper cap (toy at ~(504.7, 518.2)), so @collide on the bumper fires at least once, with a contact point near the bumper.",
           check=all_of(at_end("bumps", lambda b: b >= 1),
                        at_end("bump_point", lambda pt: math.hypot(pt[0] - 500, pt[1] - 500) <= 80)),
           scenarios=("pad",), guess=True),

    # ---- bins ---------------------------------------------------------------
    Expect(id="E29", level="L0", cite="design/Shapes Design.md#drag-and-drop step 4; toybox.py landed",
           text="Dropping the loose toy on the red bin: drops 1, tag red (not loose), binned 1, in_red 1, misses 0, over_target 'red', on_change ran once.",
           check=all_of(at(rel(0, 2), "drops", eq(1)), at(rel(0, 2), "toy0_red", eq(True)),
                        at(rel(0, 2), "toy0_loose", eq(False)), at(rel(0, 2), "binned", eq(1)),
                        at(rel(0, 2), "in_red", eq(1)), at(rel(0, 2), "changes", eq(1)),
                        at(rel(0, 2), "over_target", eq("red")), always("misses", eq(0))),
           scenarios=("red_drop",)),
    Expect(id="E30", level="L1", cite="tests/programs/toybox.py landed (centre = bin.x +- 70, bin.y; vel 0)",
           text="The landed toy sits at y = 90, x in [130, 270], velocity (0, 0), and stays put.",
           check=all_of(custom(red_landing), at(rel(0, 2), "toy0_vel", near((0, 0), 1e-9)),
                        custom(bin_y_untouched_by_drag)),
           scenarios=("red_drop",)),
    Expect(id="E31", level="L1", cite="tests/programs/toybox.py landed; harness seeded random",
           text="Guess: the landing x is 200 + uniform(-70, 70) = 166.25 (the 4th random draw).",
           check=custom(red_landing_assumption), scenarios=("red_drop",), guess=True),
    Expect(id="E32", level="L0", cite="design/Shapes Design.md#hover — exit when the target leaves the cursor",
           text="Guess (rests on E31): the toy jumps 33.75 px from the cursor, so hover exits and it is coral again.",
           check=custom(red_hover_left), scenarios=("red_drop",), guess=True),
    Expect(id="E33", level="L0", cite="tests/programs/toybox.py landed (not loose -> return); let_go (target not None)",
           text="Re-dragging the binned toy onto the blue bin changes nothing in the ledger: drops 1, still red, not blue, in_blue 0, over_target 'blue'.",
           check=all_of(at(rel(1, 2), "drops", eq(1)), at(rel(1, 2), "toy0_red", eq(True)),
                        at(rel(1, 2), "toy0_blue", eq(False)), at(rel(1, 2), "in_blue", eq(0)),
                        at(rel(1, 2), "in_red", eq(1)), at(rel(1, 2), "over_target", eq("blue"))),
           scenarios=("red_drop",), guess=True),
    Expect(id="E34", level="L1", cite="design/Shapes Design.md#drag-and-drop (grab offset taken at the crossing)",
           text="Guess (rests on E31): grabbed at its centre, the binned toy follows the pointer and stays where it was let go: (800, 90).",
           check=at(rel(1, 2), "toy0", near((800, 90), 0.5)), scenarios=("red_drop",), guess=True),
    Expect(id="E35", level="L0", cite="tests/programs/toybox.py on_key_down SPACE; @on_change",
           text="SPACE tips the bin: toy loose again, not red, binned 0, in_red 0, on_change fired a 2nd time, toy back in [80,920]x[420,580].",
           check=all_of(at(keyf("SPACE", 0, 2), "toy0_loose", eq(True)), at(keyf("SPACE", 0, 2), "toy0_red", eq(False)),
                        at(keyf("SPACE", 0, 2), "binned", eq(0)), at(keyf("SPACE", 0, 2), "in_red", eq(0)),
                        at(keyf("SPACE", 0, 2), "changes", eq(2)), custom(space_reloose)),
           scenarios=("red_drop",)),
    Expect(id="E36", level="L0", cite="tests/programs/toybox.py landed; Shapes Design drag-and-drop",
           text="Dropping on the blue bin: drops 1, tag blue, in_blue 1, binned 1, toy at y 90 with x in [730, 870], over_target 'blue'.",
           check=all_of(at_end("drops", eq(1)), at_end("toy0_blue", eq(True)), at_end("toy0_loose", eq(False)),
                        at_end("in_blue", eq(1)), at_end("binned", eq(1)), at_end("over_target", eq("blue")),
                        at_end("toy0", lambda c: 730 <= c[0] <= 870 and abs(c[1] - 90) < 1e-6)),
           scenarios=("blue_drop",)),
    Expect(id="E37", level="L0", cite="docs/pt/guide/index.html#colisao-collide (stay / exit); Colocar x viajar",
           text="Guess: the dragged toy rests on the glue strip for 2 frames on its way down, so the Toy's glue stay fires and its exit fires once.",
           check=all_of(at_end("glue_frames", lambda g: g >= 1), at_end("glue_exits", eq(1))),
           scenarios=("blue_drop",), guess=True),
    Expect(id="E38", level="L0", cite="docs/pt/guide/index.html (unregister_event removes every @on_change of the function)",
           text="After U the watcher is gone: a drop sets binned 1 and SPACE 0, but changes stays 0 and watching is False.",
           check=all_of(always("changes", eq(0)), at(rel(0, 2), "binned", eq(1)), at(rel(0, 2), "drops", eq(1)),
                        at_end("binned", eq(0)), at(keyf("U", 0, 1), "watching", eq(False))),
           scenarios=("unwatched",)),

    # ---- scanner ------------------------------------------------------------
    Expect(id="E39", level="L0", cite="design/Shapes Design.md#click; docs/pt/guide/index.html test_collision",
           text="Clicking the scanner counts loose toys overlapping it: 0 at first, 1 with the toy dropped on it, 0 after it is dragged away.",
           check=all_of(at(rel(0, 1), "scanned", eq(0)), at(rel(2, 1), "scanned", eq(1)),
                        at(rel(4, 1), "scanned", eq(0))),
           scenarios=("scanner",)),
    Expect(id="E40", level="L0", cite="design/Shapes Design.md#drag-and-drop (only droppable Graphics are drop targets)",
           text="The scanner is not droppable: both drops count as misses and the toy lands exactly at the pointer (910, 640), then (500, 200).",
           check=all_of(at_end("misses", eq(2)), always("drops", eq(0)),
                        at(rel(1, 2), "toy0", near((910, 640), 1e-6)), at_end("toy0", near((500, 200), 1e-6))),
           scenarios=("scanner",)),

    # ---- keys ---------------------------------------------------------------
    Expect(id="E41", level="L0", cite="tests/programs/toybox.py on_key_down R",
           text="R toggles st.solid False then True, and the status line shows 'ghost' while off.",
           check=all_of(at(keyf("R", 0), "solid", eq(False)), at(keyf("R", 0, 1), "status", lambda s: " ghost " in s),
                        at(keyf("R", 1), "solid", eq(True)), at_end("status", lambda s: " solid " in s)),
           scenarios=("keys",)),
    Expect(id="E42", level="L0", cite="docs/pt/guide/index.html (collision.resolve_enabled lê / escreve)",
           text="P toggles collision.resolve_enabled False then True.",
           check=all_of(at(keyf("P", 0), "resolve_enabled", eq(False)), at(keyf("P", 1), "resolve_enabled", eq(True))),
           scenarios=("keys",)),
    Expect(id="E43", level="L0", cite="tests/programs/toybox.py on_key_down U",
           text="U turns watching off; a second U leaves it off.",
           check=all_of(at(keyf("U", 0), "watching", eq(False)), at_end("watching", eq(False))),
           scenarios=("keys",)),
    Expect(id="E44", level="L0", cite="docs/pt/guide/index.html (@on_change fires on a change)",
           text="Guess: SPACE with nothing binned writes binned 0 over 0, which is no change, so changes stays 0.",
           check=always("changes", eq(0)), scenarios=("keys",), guess=True),

    # ---- drag a moving toy --------------------------------------------------
    Expect(id="E45", level="L1", cite="docs/pt/guide/index.html (pointer_pressed); toybox.py update skips pressed toys",
           text="Pressed on frame 1, the moving toy does not drift that frame (update skips a pointer_pressed toy).",
           check=custom(moving_held), scenarios=("drag_moving",), guess=True),
    Expect(id="E46", level="L1", cite="toybox.py let_go + update; frame order (input before update)",
           text="Released on empty floor it is put at (600, 250) (within one frame's travel, 160/60 px) and then drifts at most 160 px/s again (>= 40 px in 31 frames, allowing glue).",
           check=custom(moving_released), scenarios=("drag_moving",)),
]
